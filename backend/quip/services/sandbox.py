"""Sandbox manager — per-user Docker container lifecycle and execution."""

import asyncio
import io
import logging
import os
import posixpath
import shlex
import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

try:
    import docker
    from docker.errors import APIError, NotFound

    _DOCKER_AVAILABLE = True
except ImportError:
    docker = None  # type: ignore
    NotFound = Exception  # type: ignore
    APIError = Exception  # type: ignore
    _DOCKER_AVAILABLE = False
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_setting
from quip.models.sandbox import Sandbox

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "quip-sandbox:latest"
INSTALL_NETWORK = "quip-install-net"

# Host path for sandbox workspace persistence (bind-mounted into app container at /app/data/sandbox)
# This path is used as the bind-mount source when creating sandbox containers via Docker API.
# Set QUIP_HOST_SANDBOX_DIR in your .env to the absolute host path, e.g. /opt/quip/data/sandbox.
# When unset, falls back to CONTAINER_SANDBOX_DIR — files survive as long as the app container.
QUIP_HOST_SANDBOX_DIR = os.environ.get("QUIP_HOST_SANDBOX_DIR", "")
# Container-accessible path to the same directory (via docker-compose bind mount)
CONTAINER_SANDBOX_DIR = "/app/data/sandbox"


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
        # Network-enabled installs and code execution must never overlap.
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self._network_enabled_containers: set[str] = set()
        self.executor_url = os.getenv("SANDBOX_EXECUTOR_URL", "").rstrip("/")
        self.executor_token = os.getenv("EXECUTOR_TOKEN", "")
        if self.executor_url:
            self.client = None
            self._available = len(self.executor_token) >= 16
            if not self._available:
                logger.error("SANDBOX_EXECUTOR_URL is set but EXECUTOR_TOKEN is missing or too short")
            return
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

    async def healthcheck(self) -> bool:
        """Verify the configured execution backend, not just its configuration."""
        if not self._available:
            return False
        try:
            if self.executor_url:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(f"{self.executor_url}/health")
                return response.status_code == 200
            return bool(await asyncio.to_thread(self.client.ping))
        except Exception:
            return False

    async def get_or_create(self, user_id: UUID, db: AsyncSession) -> Sandbox:
        """Get existing sandbox or create a new one for the user."""
        result = await db.execute(select(Sandbox).where(Sandbox.user_id == user_id))
        sandbox = result.scalar_one_or_none()

        if sandbox:
            await self._ensure_running(sandbox, db)
            return sandbox

        # Create new sandbox
        # Full UUID hex avoids the birthday-collision ceiling of the legacy
        # eight-character names. The executor still accepts old names so
        # existing installations continue to work.
        user_key = user_id.hex
        container_name = f"quip-sandbox-{user_key}"

        if QUIP_HOST_SANDBOX_DIR:
            workspace_host_dir = f"{QUIP_HOST_SANDBOX_DIR}/{user_key}"
        else:
            # Fallback: use Docker named volume when host dir is not configured
            workspace_host_dir = f"quip-sandbox-vol-{user_key}"

        # Ensure workspace directory exists (via container bind mount path when using host dir)
        if QUIP_HOST_SANDBOX_DIR and not self.executor_url:
            os.makedirs(f"{CONTAINER_SANDBOX_DIR}/{user_key}", exist_ok=True)

        sandbox = Sandbox(
            user_id=user_id,
            container_name=container_name,
            volume_name=workspace_host_dir,
            status="creating",
        )
        db.add(sandbox)
        await db.flush()

        # Create in background thread (Docker SDK is sync)
        container_id = await asyncio.to_thread(self._create_container, container_name, workspace_host_dir, None)
        sandbox.container_id = container_id
        sandbox.status = "running"
        sandbox.last_active_at = datetime.now(UTC)
        await db.commit()
        return sandbox

    def _create_container(self, name: str, host_workspace_dir: str, image_tag: str | None) -> str:
        """Create and start a Docker container with a bind-mounted workspace (sync, run in thread)."""
        if self.executor_url:
            user_key = name.removeprefix("quip-sandbox-")
            response = self._remote_request(
                "POST",
                "/v1/container/ensure",
                json={"name": name, "user_key": user_key},
                timeout=30,
            )
            return response.json()["container_id"]

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
            volumes={host_workspace_dir: {"bind": "/workspace", "mode": "rw"}},
            mem_limit=mem_limit,
            cpu_period=100000,
            cpu_quota=int(cpu_limit * 100000),
            pids_limit=256,
            read_only=True,
            tmpfs={"/tmp": "size=100m"},
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            network_mode="none",
            user="sandbox",
            working_dir="/workspace",
            environment={
                "MPLCONFIGDIR": "/tmp/matplotlib",
                "HOME": "/tmp",
            },
            detach=True,
            stdin_open=True,
            auto_remove=True,
        )
        container.start()
        return container.id

    def _get_container(self, sandbox: Sandbox):
        """Return running container, recreating it if stopped and auto-removed."""
        if self.executor_url:
            raise RuntimeError("Direct Docker access is disabled when using the executor service")
        try:
            container = self.client.containers.get(sandbox.container_id)
            container.reload()
            network_mode = container.attrs.get("HostConfig", {}).get("NetworkMode")
            if network_mode != "none":
                logger.warning("Recreating legacy sandbox %s with networking disabled", sandbox.container_name)
                container.remove(force=True)
                sandbox.container_id = self._create_container(
                    sandbox.container_name, sandbox.volume_name, sandbox.image_tag
                )
                return self.client.containers.get(sandbox.container_id)
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            if INSTALL_NETWORK in networks and container.id not in self._network_enabled_containers:
                logger.warning("Disconnecting stale install network from %s", sandbox.container_name)
                self._restore_local_offline_network(container.id)
                container.reload()
            if container.status != "running":
                container.start()
                import time

                time.sleep(0.8)
                container.reload()
            return container
        except (NotFound, APIError):
            sandbox.container_id = self._create_container(
                sandbox.container_name, sandbox.volume_name, sandbox.image_tag
            )
            return self.client.containers.get(sandbox.container_id)

    async def _ensure_running(self, sandbox: Sandbox, db: AsyncSession) -> None:
        """Ensure the sandbox container is running."""
        sandbox.last_active_at = datetime.now(UTC)

        try:
            if self.executor_url:
                container_id = await asyncio.to_thread(
                    self._create_container,
                    sandbox.container_name,
                    sandbox.volume_name,
                    sandbox.image_tag,
                )
                sandbox.container_id = container_id
                sandbox.status = "running"
            else:
                container = await asyncio.to_thread(self._get_container, sandbox)
                if container.status == "running":
                    sandbox.status = "running"
                else:
                    sandbox.status = "error"
        except Exception as e:
            sandbox.status = "error"
            logger.error(f"Failed to ensure sandbox container: {e}")
            raise
        finally:
            await db.commit()

    async def ensure_chat_dir(self, sandbox: Sandbox, chat_id: str) -> None:
        """Create chat subdirectory in workspace if it doesn't exist (cached)."""
        safe_id = str(chat_id).replace("/", "").replace("..", "")
        cache_key = (str(sandbox.container_id or ""), safe_id)
        if cache_key in self._chat_dirs_ready:
            return
        result = await self._exec(sandbox, f"mkdir -p {shlex.quote(f'/workspace/{safe_id}')}")
        if result["exit_code"] != 0:
            raise RuntimeError(result["stderr"] or "Unable to create chat workspace")
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

        max_timeout = int(
            get_skill_setting("sandbox", "exec_timeout", None) or get_setting("sandbox_exec_timeout", "30")
        )
        timeout = max(1, min(timeout, max_timeout))
        workdir = f"/workspace/{chat_id}"

        ext = {"python": "py", "javascript": "js", "bash": "sh"}.get(language, "py")
        script_name = f"_run-{uuid4().hex}.{ext}"
        script_path = f"{workdir}/{script_name}"

        async with self._execution_lock(sandbox):
            await self._write_file_raw(sandbox, script_path, code.encode())
            try:
                before = await self._list_raw(sandbox, workdir)
                cmd_map = {
                    "python": f"python {shlex.quote(script_path)}",
                    "javascript": f"node {shlex.quote(script_path)}",
                    "bash": f"bash {shlex.quote(script_path)}",
                }
                cmd = cmd_map.get(language, f"python {shlex.quote(script_path)}")
                result = await self._exec(sandbox, cmd, workdir=workdir, timeout=timeout)
                after = await self._list_raw(sandbox, workdir)
            finally:
                await self._exec(sandbox, f"rm -f {shlex.quote(script_path)}")

        new_files = [f for f in after if f not in before and f != script_name]

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
        db: AsyncSession | None = None,
    ) -> ExecutionResult:
        """Install dependencies into the persistent workspace with temporary network access."""
        del db  # Kept in the public signature for compatibility with existing callers.
        safe_packages = self._validated_packages(packages)
        if not safe_packages:
            return ExecutionResult(stderr="No valid packages provided.", exit_code=1)
        pkg_str = shlex.join(safe_packages)

        if self.executor_url:
            async with self._execution_lock(sandbox):
                response = await asyncio.to_thread(
                    self._remote_request,
                    "POST",
                    "/v1/install",
                    json={
                        "container_id": sandbox.container_id,
                        "manager": manager,
                        "packages": safe_packages,
                    },
                    timeout=140,
                )
            payload = response.json()
            return ExecutionResult(
                stdout=payload["stdout"],
                stderr=payload["stderr"],
                exit_code=payload["exit_code"],
            )

        if manager == "pip":
            deps_dir = "/workspace/.quip/deps/python"
            cmd = f"pip install --disable-pip-version-check --upgrade --target {deps_dir} {pkg_str}"
        elif manager == "npm":
            deps_dir = "/workspace/.quip/deps/node"
            cmd = f"npm install --no-audit --no-fund --prefix {deps_dir} {pkg_str}"
        else:
            # apt not supported in read-only root — skip
            return ExecutionResult(
                stderr="apt install not supported in read-only sandbox. Use pip or npm.",
                exit_code=1,
            )
        async with self._execution_lock(sandbox):
            await self._exec(sandbox, f"mkdir -p {deps_dir}")
            try:
                await self._connect_install_network(sandbox)
                result = await self._exec(sandbox, cmd, timeout=120)
            finally:
                await self._disconnect_install_network(sandbox)

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
        if self.executor_url:
            response = self._remote_request(
                "POST",
                "/v1/file/read",
                params={"container_id": sandbox.container_id, "path": full_path},
                timeout=60,
            )
            return response.content

        container = self._get_container(sandbox)
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

    async def write_file(self, sandbox: Sandbox, chat_id: str, path: str, content: bytes) -> None:
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
                host_path.name,
                size,
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

    async def list_files(self, sandbox: Sandbox, chat_id: str, path: str = ".") -> list[FileInfo]:
        """List files in a chat's workspace directory."""
        base = f"/workspace/{chat_id}"
        if path and path != ".":
            target = _validate_path(chat_id, path)
        else:
            target = base

        # POSIX-compatible listing: works on both GNU and BusyBox find
        quoted_target = shlex.quote(target)
        result = await self._exec(
            sandbox,
            f'cd {quoted_target} 2>/dev/null || exit 1; for f in *; do [ -e "$f" ] || continue; '
            f'case "$f" in _run-*) continue;; esac; '
            f'if [ -d "$f" ]; then echo "0 d $f"; '
            f'else size=$(wc -c < "$f" | tr -d "[:space:]"); echo "$size f $f"; fi; done',
        )
        if result["exit_code"] != 0:
            raise FileNotFoundError(f"Sandbox path not found: {path}")
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
            files.append(
                FileInfo(
                    name=name,
                    path=posixpath.join(path if path != "." else "", name),
                    size=int(size) if size.isdigit() else 0,
                    is_dir=ftype == "d",
                )
            )
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
        if self.executor_url:
            try:
                self._remote_request(
                    "POST",
                    "/v1/container/stop",
                    json={"container_id": container_id},
                    timeout=20,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
            return
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
        except NotFound:
            pass

    async def destroy(self, user_id: UUID, db: AsyncSession) -> None:
        """Destroy sandbox completely — container, volume, committed image, DB record."""
        result = await db.execute(select(Sandbox).where(Sandbox.user_id == user_id))
        sandbox = result.scalar_one_or_none()
        if not sandbox:
            return

        await asyncio.to_thread(self._destroy_sync, sandbox)
        await db.delete(sandbox)
        await db.commit()

    def _destroy_sync(self, sandbox: Sandbox) -> None:
        if self.executor_url:
            user_key = sandbox.container_name.removeprefix("quip-sandbox-")
            self._remote_request(
                "POST",
                "/v1/container/destroy",
                json={"container_id": sandbox.container_id, "user_key": user_key},
                timeout=30,
            )
            return

        # Remove container
        try:
            container = self.client.containers.get(sandbox.container_id)
            container.remove(force=True)
        except (NotFound, APIError):
            pass

        # Remove workspace directory / volume
        if sandbox.volume_name:
            if QUIP_HOST_SANDBOX_DIR:
                # Host bind mount — delete directory on host via container path
                uid_short = (
                    sandbox.volume_name.rstrip("/").split("/")[-1]
                    if "/" in sandbox.volume_name
                    else sandbox.volume_name
                )
                if uid_short:
                    shutil.rmtree(f"{CONTAINER_SANDBOX_DIR}/{uid_short}", ignore_errors=True)
            else:
                # Named Docker volume — remove it
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

    def _remote_request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = 60,
        **kwargs,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self.executor_token}"
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method,
                f"{self.executor_url}{path}",
                headers=headers,
                **kwargs,
            )
        response.raise_for_status()
        return response

    def _execution_lock(self, sandbox: Sandbox) -> asyncio.Lock:
        key = str(sandbox.id or sandbox.user_id or sandbox.container_name)
        return self._execution_locks.setdefault(key, asyncio.Lock())

    @staticmethod
    def _validated_packages(packages: list[str]) -> list[str]:
        if len(packages) > 50:
            raise ValueError("Too many packages requested")
        result = []
        for package in packages:
            value = package.strip()
            if not value or len(value) > 200 or value.startswith("-"):
                raise ValueError(f"Invalid package specifier: {package!r}")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(f"Invalid package specifier: {package!r}")
            result.append(value)
        return result

    async def _exec(
        self,
        sandbox: Sandbox,
        cmd: str,
        workdir: str | None = None,
        timeout: int = 30,
    ) -> dict:
        """Execute a command inside the container."""
        return await asyncio.to_thread(self._exec_sync, sandbox, cmd, workdir, timeout)

    def _exec_sync(
        self,
        sandbox: Sandbox,
        cmd: str,
        workdir: str | None = None,
        timeout: int = 30,
    ) -> dict:
        try:
            if self.executor_url:
                response = self._remote_request(
                    "POST",
                    "/v1/exec",
                    json={
                        "container_id": sandbox.container_id,
                        "command": cmd,
                        "workdir": workdir,
                        "timeout": max(1, int(timeout)),
                    },
                    timeout=max(15, int(timeout) + 10),
                )
                return response.json()

            container = self._get_container(sandbox)
            timeout_seconds = max(1, int(timeout))
            exit_code, output = container.exec_run(
                [
                    "timeout",
                    "--signal=TERM",
                    "--kill-after=2s",
                    f"{timeout_seconds}s",
                    "bash",
                    "-lc",
                    cmd,
                ],
                workdir=workdir,
                demux=True,
                environment={
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": "/workspace/.quip/deps/python",
                    "NODE_PATH": "/workspace/.quip/deps/node/node_modules",
                    "PATH": "/workspace/.quip/deps/node/node_modules/.bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
                },
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

    async def _write_file_raw(self, sandbox: Sandbox, full_path: str, content: bytes) -> None:
        await asyncio.to_thread(self._write_file_sync, sandbox, full_path, content)

    def _write_file_sync(self, sandbox: Sandbox, full_path: str, content: bytes) -> None:
        if self.executor_url:
            self._remote_request(
                "POST",
                "/v1/file/write",
                params={"container_id": sandbox.container_id, "path": full_path},
                content=content,
                headers={"Content-Type": "application/octet-stream"},
                timeout=120,
            )
            return

        container = self._get_container(sandbox)
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
        if self.executor_url:
            raise RuntimeError("Remote installs must use the executor's atomic install endpoint")

        # Ensure install network exists
        try:
            network = self.client.networks.get(INSTALL_NETWORK)
        except NotFound:
            network = self.client.networks.create(INSTALL_NETWORK, driver="bridge")
        container = self._get_container(sandbox)
        sandbox.container_id = container.id
        self._network_enabled_containers.add(container.id)
        try:
            try:
                self.client.networks.get("none").disconnect(container.id, force=True)
            except (NotFound, APIError):
                pass
            network.connect(container.id)
        except Exception:
            self._restore_local_offline_network(container.id)
            raise

    async def _disconnect_install_network(self, sandbox: Sandbox) -> None:
        await asyncio.to_thread(self._disconnect_network_sync, sandbox)

    def _disconnect_network_sync(self, sandbox: Sandbox) -> None:
        if self.executor_url:
            raise RuntimeError("Remote installs must use the executor's atomic install endpoint")

        self._restore_local_offline_network(sandbox.container_id)

    def _restore_local_offline_network(self, container_id: str) -> None:
        try:
            self.client.networks.get(INSTALL_NETWORK).disconnect(container_id, force=True)
        except (NotFound, APIError):
            pass
        try:
            self.client.networks.get("none").connect(container_id)
        except (NotFound, APIError):
            pass
        finally:
            self._network_enabled_containers.discard(container_id)


# Singleton
sandbox_manager = SandboxManager()


async def sandbox_cleanup_loop() -> None:
    """Background task: stop idle containers, then destroy stopped ones after a grace period."""
    from quip.database import async_session

    while True:
        try:
            await asyncio.sleep(60)
            if not sandbox_manager.available:
                continue

            from quip.services.skill_store import get_skill_setting

            # Phase 1: stop running containers idle longer than idle_timeout
            idle_timeout = int(
                get_skill_setting("sandbox", "idle_timeout", None) or get_setting("sandbox_idle_timeout", "600")
            )
            stop_cutoff = datetime.now(UTC).timestamp() - idle_timeout

            async with async_session() as db:
                result = await db.execute(select(Sandbox).where(Sandbox.status == "running"))
                for sb in result.scalars().all():
                    if sb.last_active_at and sb.last_active_at.timestamp() < stop_cutoff:
                        logger.info(f"Stopping idle sandbox: {sb.container_name}")
                        await sandbox_manager.stop(sb, db)

            # Stopping a runtime is safe; deleting workspace files referenced by old
            # chats is not. Destructive cleanup is opt-in only.
            destroy_timeout = int(
                get_skill_setting("sandbox", "destroy_timeout", None) or get_setting("sandbox_destroy_timeout", "0")
            )
            if destroy_timeout <= 0:
                continue
            destroy_cutoff = datetime.now(UTC).timestamp() - destroy_timeout

            async with async_session() as db:
                result = await db.execute(select(Sandbox).where(Sandbox.status == "stopped"))
                for sb in result.scalars().all():
                    if sb.last_active_at and sb.last_active_at.timestamp() < destroy_cutoff:
                        logger.info(f"Destroying stale stopped sandbox: {sb.container_name}")
                        await sandbox_manager.destroy(sb.user_id, db)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Sandbox cleanup error: {e}")
