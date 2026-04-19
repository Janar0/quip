"""Sandbox manager — per-user Docker container lifecycle and execution."""
import asyncio
import io
import json
import logging
import posixpath
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

try:
    import docker
    from docker.errors import NotFound, APIError
    _DOCKER_AVAILABLE = True
except ImportError:
    docker = None  # type: ignore
    NotFound = Exception  # type: ignore
    APIError = Exception  # type: ignore
    _DOCKER_AVAILABLE = False
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.sandbox import Sandbox
from quip.services.config import get_setting

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "quip-sandbox:latest"
INSTALL_NETWORK = "quip-install-net"


@dataclass
class ExecutionResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    files_created: list[str] = field(default_factory=list)


@dataclass
class FileInfo:
    name: str = ""
    path: str = ""
    size: int = 0
    is_dir: bool = False


def _validate_path(chat_id: str, path: str) -> str:
    """Resolve path and ensure it stays within /workspace/{chat_id}/."""
    base = f"/workspace/{chat_id}"
    # Normalize: strip leading slash, resolve .. etc.
    clean_path = path.lstrip("/")
    resolved = posixpath.normpath(posixpath.join(base, clean_path))
    if not (resolved == base or resolved.startswith(base + "/")):
        raise ValueError(f"Path escapes sandbox: {path}")
    return resolved


class SandboxManager:
    def __init__(self):
        # Cache of (container_id, chat_id) tuples for which mkdir already ran
        # this process. Eliminates a Docker exec on every chat turn.
        self._chat_dirs_ready: set[tuple[str, str]] = set()
        if not _DOCKER_AVAILABLE:
            logger.warning("Docker SDK not installed (pip install docker)")
            self.client = None
            self._available = False
            return
        try:
            self.client = docker.from_env()
            self._available = True
        except Exception as e:
            logger.warning(f"Docker not available: {e}")
            self.client = None
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def get_or_create(self, user_id: UUID, db: AsyncSession) -> Sandbox:
        """Get existing sandbox or create a new one for the user."""
        result = await db.execute(
            select(Sandbox).where(Sandbox.user_id == user_id)
        )
        sandbox = result.scalar_one_or_none()

        if sandbox:
            await self._ensure_running(sandbox, db)
            return sandbox

        # Create new sandbox
        uid_short = str(user_id)[:8]
        container_name = f"quip-sandbox-{uid_short}"
        volume_name = f"quip-sandbox-vol-{uid_short}"

        sandbox = Sandbox(
            user_id=user_id,
            container_name=container_name,
            volume_name=volume_name,
            status="creating",
        )
        db.add(sandbox)
        await db.flush()

        # Create in background thread (Docker SDK is sync)
        container_id = await asyncio.to_thread(
            self._create_container, container_name, volume_name, None
        )
        sandbox.container_id = container_id
        sandbox.status = "running"
        sandbox.last_active_at = datetime.now(timezone.utc)
        await db.commit()
        return sandbox

    def _create_container(
        self, name: str, volume_name: str, image_tag: Optional[str]
    ) -> str:
        """Create and start a Docker container (sync, run in thread)."""
        image = image_tag or SANDBOX_IMAGE
        from quip.services.skill_store import get_skill_setting
        mem_limit = get_skill_setting("sandbox", "memory_limit", None) or get_setting("sandbox_memory_limit", "512m")
        cpu_limit = float(get_skill_setting("sandbox", "cpu_limit", None) or get_setting("sandbox_cpu_limit", "1.0"))

        # Remove old container if exists
        try:
            old = self.client.containers.get(name)
            old.remove(force=True)
        except NotFound:
            pass

        container = self.client.containers.create(
            image=image,
            name=name,
            volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
            mem_limit=mem_limit,
            cpu_period=100000,
            cpu_quota=int(cpu_limit * 100000),
            pids_limit=256,
            read_only=True,
            tmpfs={"/tmp": "size=100m"},
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            user="sandbox",
            working_dir="/workspace",
            environment={
                "MPLCONFIGDIR": "/tmp/matplotlib",
                "HOME": "/tmp",
            },
            detach=True,
            stdin_open=True,
        )
        container.start()
        return container.id

    async def _ensure_running(self, sandbox: Sandbox, db: AsyncSession) -> None:
        """Ensure the sandbox container is running."""
        sandbox.last_active_at = datetime.now(timezone.utc)

        if sandbox.status == "running" and sandbox.container_id:
            # Verify container actually exists and is running
            try:
                container = await asyncio.to_thread(
                    self.client.containers.get, sandbox.container_id
                )
                if container.status == "running":
                    await db.commit()
                    return
                # Container exists but not running — try to start it
                try:
                    await asyncio.to_thread(container.start)
                    await db.commit()
                    return
                except Exception:
                    # Can't start — will recreate below
                    logger.info(f"Cannot restart container {sandbox.container_id}, recreating")
            except (NotFound, APIError):
                logger.info(f"Container {sandbox.container_id} not found, recreating")

        # Recreate container from committed image or base
        try:
            container_id = await asyncio.to_thread(
                self._create_container,
                sandbox.container_name,
                sandbox.volume_name,
                sandbox.image_tag,
            )
            sandbox.container_id = container_id
            sandbox.status = "running"
        except Exception as e:
            sandbox.status = "error"
            logger.error(f"Failed to create container: {e}")
            raise
        finally:
            await db.commit()

    async def ensure_chat_dir(self, sandbox: Sandbox, chat_id: str) -> None:
        """Create chat subdirectory in workspace if it doesn't exist (cached)."""
        safe_id = str(chat_id).replace("/", "").replace("..", "")
        cache_key = (str(sandbox.container_id or ""), safe_id)
        if cache_key in self._chat_dirs_ready:
            return
        await self._exec(sandbox, f"mkdir -p /workspace/{safe_id}")
        self._chat_dirs_ready.add(cache_key)

    async def execute(
        self,
        sandbox: Sandbox,
        chat_id: str,
        code: str,
        language: str,
        timeout: int = 30,
    ) -> ExecutionResult:
        """Execute code in the sandbox, within the chat's directory."""
        from quip.services.skill_store import get_skill_setting
        max_timeout = int(get_skill_setting("sandbox", "exec_timeout", None) or get_setting("sandbox_exec_timeout", "30"))
        timeout = min(timeout, max_timeout)
        workdir = f"/workspace/{chat_id}"

        ext = {"python": "py", "javascript": "js", "bash": "sh"}.get(language, "py")
        script_path = f"{workdir}/_run.{ext}"

        # Write code to file
        await self._write_file_raw(sandbox, script_path, code.encode())

        # Get file list before execution
        before = await self._list_raw(sandbox, workdir)

        # Execute
        cmd_map = {
            "python": f"python {script_path}",
            "javascript": f"node {script_path}",
            "bash": f"bash {script_path}",
        }
        cmd = cmd_map.get(language, f"python {script_path}")
        result = await self._exec(sandbox, cmd, workdir=workdir, timeout=timeout)

        # Get file list after execution
        after = await self._list_raw(sandbox, workdir)

        # Detect new files
        new_files = [f for f in after if f not in before and not f.startswith("_run.")]

        # Clean up script
        await self._exec(sandbox, f"rm -f {script_path}")

        return ExecutionResult(
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
            files_created=new_files,
        )

    async def install_packages(
        self,
        sandbox: Sandbox,
        packages: list[str],
        manager: str = "pip",
        db: Optional[AsyncSession] = None,
    ) -> ExecutionResult:
        """Install packages with temporary network access, then commit."""
        # Sanitize package names
        safe_packages = [p.replace(";", "").replace("&", "").replace("|", "") for p in packages]
        pkg_str = " ".join(safe_packages)

        if manager == "pip":
            cmd = f"pip install --user {pkg_str}"
        elif manager == "npm":
            cmd = f"npm install -g {pkg_str}"
        else:
            # apt not supported in read-only root — skip
            return ExecutionResult(
                stderr="apt install not supported in read-only sandbox. Use pip or npm.",
                exit_code=1,
            )
        result = await self._exec(sandbox, cmd, timeout=120)

        # Commit container to preserve installed packages
        if result["exit_code"] == 0:
            await self._commit(sandbox, db)

        return ExecutionResult(
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
        )

    async def read_file(self, sandbox: Sandbox, chat_id: str, path: str) -> bytes:
        """Read a file from the sandbox."""
        full_path = _validate_path(chat_id, path)
        return await asyncio.to_thread(self._read_file_sync, sandbox, full_path)

    def _read_file_sync(self, sandbox: Sandbox, full_path: str) -> bytes:
        container = self.client.containers.get(sandbox.container_id)
        bits, _ = container.get_archive(full_path)
        # get_archive returns a tar stream
        buf = io.BytesIO()
        for chunk in bits:
            buf.write(chunk)
        buf.seek(0)
        with tarfile.open(fileobj=buf) as tar:
            member = tar.getmembers()[0]
            f = tar.extractfile(member)
            return f.read() if f else b""

    async def write_file(
        self, sandbox: Sandbox, chat_id: str, path: str, content: bytes
    ) -> None:
        """Write a file to the sandbox."""
        full_path = _validate_path(chat_id, path)
        await self._write_file_raw(sandbox, full_path, content)

    async def copy_host_file(
        self,
        sandbox: Sandbox,
        chat_id: str,
        host_path: Path,
        dest_name: str,
    ) -> bool:
        """Copy a file from the host filesystem into the chat workspace.

        Returns True if the file is present in the workdir after the call
        (either because it was copied now or was already there with matching
        size). Returns False if the copy was skipped (source missing, too
        large) or failed.
        """
        if not host_path.exists() or not host_path.is_file():
            logger.warning("copy_host_file: source missing %s", host_path)
            return False

        MAX_COPY_BYTES = 50 * 1024 * 1024
        size = host_path.stat().st_size
        if size > MAX_COPY_BYTES:
            logger.warning(
                "copy_host_file: %s too large (%d bytes), skipping sandbox copy",
                host_path.name, size,
            )
            return False

        try:
            existing = await self.list_files(sandbox, chat_id, ".")
            for f in existing:
                if f.name == dest_name and f.size == size:
                    return True
        except Exception:
            pass

        content = await asyncio.to_thread(host_path.read_bytes)
        await self.write_file(sandbox, chat_id, dest_name, content)
        return True

    async def list_files(
        self, sandbox: Sandbox, chat_id: str, path: str = "."
    ) -> list[FileInfo]:
        """List files in a chat's workspace directory."""
        base = f"/workspace/{chat_id}"
        if path and path != ".":
            target = _validate_path(chat_id, path)
        else:
            target = base

        result = await self._exec(
            sandbox,
            f"find {target} -maxdepth 1 -not -name '_run.*' -printf '%s %y %f\\n'",
        )
        files = []
        for line in result["stdout"].strip().split("\n"):
            if not line:
                continue
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            size, ftype, name = parts
            if name == "." or name == posixpath.basename(target):
                continue
            files.append(FileInfo(
                name=name,
                path=posixpath.join(path if path != "." else "", name),
                size=int(size) if size.isdigit() else 0,
                is_dir=ftype == "d",
            ))
        return files

    async def stop(self, sandbox: Sandbox, db: AsyncSession) -> None:
        """Stop the sandbox container."""
        try:
            await asyncio.to_thread(self._stop_sync, sandbox.container_id)
        except Exception as e:
            logger.warning(f"Error stopping sandbox {sandbox.container_name}: {e}")
        sandbox.status = "stopped"
        await db.commit()

    def _stop_sync(self, container_id: str) -> None:
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
        except NotFound:
            pass

    async def destroy(self, user_id: UUID, db: AsyncSession) -> None:
        """Destroy sandbox completely — container, volume, committed image, DB record."""
        result = await db.execute(
            select(Sandbox).where(Sandbox.user_id == user_id)
        )
        sandbox = result.scalar_one_or_none()
        if not sandbox:
            return

        await asyncio.to_thread(self._destroy_sync, sandbox)
        await db.delete(sandbox)
        await db.commit()

    def _destroy_sync(self, sandbox: Sandbox) -> None:
        # Remove container
        try:
            container = self.client.containers.get(sandbox.container_id)
            container.remove(force=True)
        except (NotFound, APIError):
            pass

        # Remove volume
        try:
            vol = self.client.volumes.get(sandbox.volume_name)
            vol.remove(force=True)
        except (NotFound, APIError):
            pass

        # Remove committed image
        if sandbox.image_tag:
            try:
                self.client.images.remove(sandbox.image_tag, force=True)
            except (NotFound, APIError):
                pass

    async def delete_chat_files(self, sandbox: Sandbox, chat_id: str) -> None:
        """Delete a specific chat's workspace directory."""
        safe_id = str(chat_id).replace("/", "").replace("..", "")
        await self._exec(sandbox, f"rm -rf /workspace/{safe_id}")

    # --- Internal helpers ---

    async def _exec(
        self,
        sandbox: Sandbox,
        cmd: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
    ) -> dict:
        """Execute a command inside the container."""
        return await asyncio.to_thread(
            self._exec_sync, sandbox.container_id, cmd, workdir, timeout
        )

    def _exec_sync(
        self,
        container_id: str,
        cmd: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
    ) -> dict:
        try:
            container = self.client.containers.get(container_id)
            # Auto-restart if container stopped between calls
            if container.status != "running":
                logger.info(f"Container {container_id[:12]} not running (status={container.status}), restarting")
                container.start()
                import time
                time.sleep(0.8)
                container.reload()
                if container.status != "running":
                    return {"stdout": "", "stderr": "Container failed to restart", "exit_code": 1}
            exit_code, output = container.exec_run(
                ["bash", "-c", cmd],
                workdir=workdir,
                demux=True,
                environment={"PYTHONDONTWRITEBYTECODE": "1"},
            )
            stdout = (output[0] or b"").decode("utf-8", errors="replace")
            stderr = (output[1] or b"").decode("utf-8", errors="replace")
            # Truncate very long output
            max_len = 50000
            if len(stdout) > max_len:
                stdout = stdout[:max_len] + "\n... (truncated)"
            if len(stderr) > max_len:
                stderr = stderr[:max_len] + "\n... (truncated)"
            return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": 1}

    async def _write_file_raw(
        self, sandbox: Sandbox, full_path: str, content: bytes
    ) -> None:
        await asyncio.to_thread(self._write_file_sync, sandbox, full_path, content)

    def _write_file_sync(
        self, sandbox: Sandbox, full_path: str, content: bytes
    ) -> None:
        container = self.client.containers.get(sandbox.container_id)
        dirname = posixpath.dirname(full_path)
        filename = posixpath.basename(full_path)

        # Build tar archive with the file
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        buf.seek(0)
        container.put_archive(dirname, buf)

    async def _list_raw(self, sandbox: Sandbox, workdir: str) -> set[str]:
        result = await self._exec(sandbox, f"ls -1 {workdir}")
        return set(result["stdout"].strip().split("\n")) if result["stdout"].strip() else set()

    async def _connect_install_network(self, sandbox: Sandbox) -> None:
        await asyncio.to_thread(self._connect_network_sync, sandbox)

    def _connect_network_sync(self, sandbox: Sandbox) -> None:
        # Ensure install network exists
        try:
            network = self.client.networks.get(INSTALL_NETWORK)
        except NotFound:
            network = self.client.networks.create(INSTALL_NETWORK, driver="bridge")
        network.connect(sandbox.container_id)

    async def _disconnect_install_network(self, sandbox: Sandbox) -> None:
        await asyncio.to_thread(self._disconnect_network_sync, sandbox)

    def _disconnect_network_sync(self, sandbox: Sandbox) -> None:
        try:
            network = self.client.networks.get(INSTALL_NETWORK)
            network.disconnect(sandbox.container_id, force=True)
        except (NotFound, APIError):
            pass

    async def _commit(
        self, sandbox: Sandbox, db: Optional[AsyncSession] = None
    ) -> None:
        """Commit container state to a per-user image tag."""
        tag = f"quip-sandbox-{sandbox.container_name}:latest"
        await asyncio.to_thread(self._commit_sync, sandbox.container_id, tag)
        sandbox.image_tag = tag
        if db:
            await db.commit()

    def _commit_sync(self, container_id: str, tag: str) -> None:
        container = self.client.containers.get(container_id)
        repo, tag_name = tag.rsplit(":", 1)
        container.commit(repository=repo, tag=tag_name)


# Singleton
sandbox_manager = SandboxManager()


async def sandbox_cleanup_loop() -> None:
    """Background task: stop idle sandbox containers."""
    from quip.database import async_session

    while True:
        try:
            await asyncio.sleep(60)
            if not sandbox_manager.available:
                continue

            from quip.services.skill_store import get_skill_setting
            timeout_seconds = int(get_skill_setting("sandbox", "idle_timeout", None) or get_setting("sandbox_idle_timeout", "600"))
            cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds

            async with async_session() as db:
                result = await db.execute(
                    select(Sandbox).where(Sandbox.status == "running")
                )
                for sb in result.scalars().all():
                    if sb.last_active_at and sb.last_active_at.timestamp() < cutoff:
                        logger.info(f"Stopping idle sandbox: {sb.container_name}")
                        await sandbox_manager.stop(sb, db)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Sandbox cleanup error: {e}")
