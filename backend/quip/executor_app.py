"""Internal Docker executor with a deliberately narrow, sandbox-only API.

The public web process never receives the Docker socket. This service accepts
operations only for containers that it created and labelled itself.
"""

import hmac
import io
import os
import posixpath
import re
import shlex
import shutil
import tarfile
import threading
from pathlib import Path
from typing import Literal

import docker
from docker.errors import APIError, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

EXECUTOR_TOKEN = os.getenv("EXECUTOR_TOKEN", "")
HOST_SANDBOX_DIR = os.getenv("QUIP_HOST_SANDBOX_DIR", "")
MOUNTED_SANDBOX_DIR = Path(os.getenv("EXECUTOR_WORKSPACE_ROOT", "/executor/workspaces"))
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "quip-sandbox:latest")
INSTALL_NETWORK = "quip-install-net"
MANAGED_LABEL = "dev.quip.sandbox"
MAX_WRITE_BYTES = 100 * 1024 * 1024
NAME_RE = re.compile(r"^quip-sandbox-([0-9a-f]{8}|[0-9a-f]{32})$")

if len(EXECUTOR_TOKEN) < 16:
    raise RuntimeError("EXECUTOR_TOKEN must contain at least 16 characters")
if not HOST_SANDBOX_DIR.startswith("/"):
    raise RuntimeError("QUIP_HOST_SANDBOX_DIR must be an absolute host path")

client = docker.from_env()
network_enabled: set[str] = set()
install_locks: dict[str, threading.Lock] = {}
install_locks_guard = threading.Lock()

app = FastAPI(
    title="QUIP internal executor",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {EXECUTOR_TOKEN}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


class ContainerRequest(BaseModel):
    name: str
    user_key: str = Field(pattern=r"^(?:[0-9a-f]{8}|[0-9a-f]{32})$")


class ExecRequest(BaseModel):
    container_id: str
    command: str = Field(max_length=1_000_000)
    workdir: str | None = None
    timeout: int = Field(default=30, ge=1, le=300)


class ContainerRef(BaseModel):
    container_id: str


class DestroyRequest(ContainerRef):
    user_key: str = Field(pattern=r"^(?:[0-9a-f]{8}|[0-9a-f]{32})$")


class InstallRequest(ContainerRef):
    manager: Literal["pip", "npm"]
    packages: list[str] = Field(min_length=1, max_length=50)


def _validate_name(name: str, user_key: str) -> None:
    match = NAME_RE.fullmatch(name)
    if match is None or match.group(1) != user_key:
        raise HTTPException(status_code=400, detail="Invalid sandbox identity")


def _validate_workspace_path(path: str) -> str:
    normalized = posixpath.normpath(path)
    if normalized != "/workspace" and not normalized.startswith("/workspace/"):
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return normalized


def _managed_container(reference: str):
    try:
        container = client.containers.get(reference)
        container.reload()
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Sandbox not found") from exc
    labels = container.attrs.get("Config", {}).get("Labels") or {}
    match = NAME_RE.fullmatch(container.name)
    if (
        labels.get(MANAGED_LABEL) != "true"
        or match is None
        or labels.get("dev.quip.user_key") != match.group(1)
    ):
        raise HTTPException(status_code=403, detail="Container is not managed by QUIP")

    networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
    if INSTALL_NETWORK in networks and container.id not in network_enabled:
        _restore_offline_network(container.id)
        container.reload()
    return container


def _restore_offline_network(container_id: str) -> None:
    """Leave a sandbox attached only to Docker's special `none` network."""
    try:
        client.networks.get(INSTALL_NETWORK).disconnect(container_id, force=True)
    except (NotFound, APIError):
        pass
    try:
        client.networks.get("none").connect(container_id)
    except (NotFound, APIError):
        # `already exists` is the normal idempotent case.
        pass
    finally:
        network_enabled.discard(container_id)


def _create_container(name: str, user_key: str):
    _validate_name(name, user_key)
    mounted_dir = MOUNTED_SANDBOX_DIR / user_key
    mounted_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(mounted_dir, 1000, 1000)
    except OSError as exc:
        # A root-owned directory would make the non-root sandbox appear to
        # start successfully but every write would fail later.
        if mounted_dir.stat().st_uid != 1000:
            raise RuntimeError("Executor cannot assign the sandbox workspace to uid 1000") from exc

    host_dir = f"{HOST_SANDBOX_DIR.rstrip('/')}/{user_key}"
    container = client.containers.create(
        image=SANDBOX_IMAGE,
        name=name,
        labels={MANAGED_LABEL: "true", "dev.quip.user_key": user_key},
        volumes={host_dir: {"bind": "/workspace", "mode": "rw"}},
        mem_limit=os.getenv("SANDBOX_MEMORY_LIMIT", "512m"),
        cpu_period=100000,
        cpu_quota=int(float(os.getenv("SANDBOX_CPU_LIMIT", "1.0")) * 100000),
        pids_limit=256,
        read_only=True,
        tmpfs={"/tmp": "rw,nosuid,size=100m"},
        security_opt=["no-new-privileges"],
        cap_drop=["ALL"],
        network_mode="none",
        user="sandbox",
        working_dir="/workspace",
        environment={"MPLCONFIGDIR": "/tmp/matplotlib", "HOME": "/tmp"},
        detach=True,
        stdin_open=True,
        auto_remove=True,
    )
    container.start()
    return container


@app.get("/health")
def health():
    try:
        client.ping()
        client.images.get(SANDBOX_IMAGE)
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Docker executor unavailable") from exc


@app.post("/v1/container/ensure", dependencies=[Depends(authorize)])
def ensure_container(data: ContainerRequest):
    _validate_name(data.name, data.user_key)
    try:
        container = client.containers.get(data.name)
        container.reload()
        labels = container.attrs.get("Config", {}).get("Labels") or {}
        network_mode = container.attrs.get("HostConfig", {}).get("NetworkMode")
        if labels.get(MANAGED_LABEL) != "true" or labels.get("dev.quip.user_key") != data.user_key:
            raise HTTPException(status_code=403, detail="Conflicting container is not managed by QUIP")
        if network_mode != "none":
            container.remove(force=True)
            container = _create_container(data.name, data.user_key)
        elif container.status != "running":
            container.start()
            container.reload()
        else:
            container = _managed_container(container.id)
    except NotFound:
        container = _create_container(data.name, data.user_key)
    return {"container_id": container.id, "status": container.status}


@app.post("/v1/exec", dependencies=[Depends(authorize)])
def execute(data: ExecRequest):
    container = _managed_container(data.container_id)
    workdir = _validate_workspace_path(data.workdir) if data.workdir else None
    # Serialize with package installation so user code can never run while the
    # temporary install network is attached.
    with _install_lock(container.id):
        exit_code, output = container.exec_run(
            [
                "timeout",
                "--signal=TERM",
                "--kill-after=2s",
                f"{data.timeout}s",
                "bash",
                "-lc",
                data.command,
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
    stdout = (output[0] or b"").decode("utf-8", errors="replace")[:50000]
    stderr = (output[1] or b"").decode("utf-8", errors="replace")[:50000]
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}


@app.post("/v1/file/read", dependencies=[Depends(authorize)])
def read_file(container_id: str, path: str):
    container = _managed_container(container_id)
    full_path = _validate_workspace_path(path)
    try:
        bits, _ = container.get_archive(full_path)
        buffer = io.BytesIO()
        for chunk in bits:
            buffer.write(chunk)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer) as archive:
            member = archive.getmembers()[0]
            extracted = archive.extractfile(member)
            content = extracted.read() if extracted else b""
    except (NotFound, APIError, KeyError, tarfile.TarError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    return Response(content=content, media_type="application/octet-stream")


@app.post("/v1/file/write", dependencies=[Depends(authorize)])
async def write_file(container_id: str, path: str, request: Request):
    container = _managed_container(container_id)
    full_path = _validate_workspace_path(path)
    content = await request.body()
    if len(content) > MAX_WRITE_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    dirname = posixpath.dirname(full_path)
    filename = posixpath.basename(full_path)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name=filename)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    buffer.seek(0)
    if not container.put_archive(dirname, buffer):
        raise HTTPException(status_code=500, detail="File write failed")
    return {"status": "ok"}


def _disconnect_install_network(container_id: str) -> None:
    _restore_offline_network(container_id)


def _install_lock(container_id: str) -> threading.Lock:
    with install_locks_guard:
        return install_locks.setdefault(container_id, threading.Lock())


def _validated_packages(packages: list[str]) -> list[str]:
    result = []
    for package in packages:
        value = package.strip()
        if not value or len(value) > 200 or value.startswith("-"):
            raise HTTPException(status_code=400, detail="Invalid package specifier")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise HTTPException(status_code=400, detail="Invalid package specifier")
        result.append(value)
    return result


@app.post("/v1/install", dependencies=[Depends(authorize)])
def install_packages(data: InstallRequest):
    """Install only validated package specs, with network attached for this call."""
    container = _managed_container(data.container_id)
    packages = shlex.join(_validated_packages(data.packages))
    if data.manager == "pip":
        deps_dir = "/workspace/.quip/deps/python"
        command = f"mkdir -p {deps_dir} && pip install --disable-pip-version-check --upgrade --target {deps_dir} {packages}"
    else:
        deps_dir = "/workspace/.quip/deps/node"
        command = f"mkdir -p {deps_dir} && npm install --no-audit --no-fund --prefix {deps_dir} {packages}"

    with _install_lock(container.id):
        try:
            try:
                network = client.networks.get(INSTALL_NETWORK)
            except NotFound:
                network = client.networks.create(INSTALL_NETWORK, driver="bridge")
            network_enabled.add(container.id)
            try:
                client.networks.get("none").disconnect(container.id, force=True)
            except (NotFound, APIError):
                pass
            network.connect(container.id)
            exit_code, output = container.exec_run(
                [
                    "timeout",
                    "--signal=TERM",
                    "--kill-after=2s",
                    "120s",
                    "bash",
                    "-lc",
                    command,
                ],
                workdir="/workspace",
                demux=True,
            )
        except APIError as exc:
            raise HTTPException(status_code=409, detail="Package installation failed to start") from exc
        finally:
            _disconnect_install_network(container.id)

    stdout = (output[0] or b"").decode("utf-8", errors="replace")[:50000]
    stderr = (output[1] or b"").decode("utf-8", errors="replace")[:50000]
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}


@app.post("/v1/container/stop", dependencies=[Depends(authorize)])
def stop_container(data: ContainerRef):
    container = _managed_container(data.container_id)
    container.stop(timeout=10)
    return {"status": "stopped"}


@app.post("/v1/container/destroy", dependencies=[Depends(authorize)])
def destroy_container(data: DestroyRequest):
    try:
        container = _managed_container(data.container_id)
        labels = container.attrs.get("Config", {}).get("Labels") or {}
        if labels.get("dev.quip.user_key") != data.user_key:
            raise HTTPException(status_code=403, detail="Sandbox identity mismatch")
        try:
            container.remove(force=True)
        except (NotFound, APIError):
            pass
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    shutil.rmtree(MOUNTED_SANDBOX_DIR / data.user_key, ignore_errors=True)
    return {"status": "destroyed"}
