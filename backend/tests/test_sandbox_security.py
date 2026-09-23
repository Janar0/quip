import asyncio
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import quip.services.sandbox as sandbox_module
from quip.database import Base
from quip.models.sandbox import Sandbox
from quip.models.user import User
from quip.services.sandbox import SandboxManager


def bare_manager() -> SandboxManager:
    manager = SandboxManager.__new__(SandboxManager)
    manager._execution_locks = {}
    manager._network_enabled_containers = set()
    manager.executor_url = ""
    manager.executor_token = ""
    return manager


def test_exec_wraps_command_in_hard_timeout_and_dependency_env():
    manager = bare_manager()

    class Container:
        def __init__(self):
            self.call = None

        def exec_run(self, command, **kwargs):
            self.call = (command, kwargs)
            return 124, (b"", b"timed out")

    container = Container()
    manager._get_container = lambda _sandbox: container

    result = manager._exec_sync(SimpleNamespace(), "python job.py", "/workspace/chat", 7)

    command, kwargs = container.call
    assert command[:4] == ["timeout", "--signal=TERM", "--kill-after=2s", "7s"]
    assert command[-3:] == ["bash", "-lc", "python job.py"]
    assert kwargs["environment"]["PYTHONPATH"] == "/workspace/.quip/deps/python"
    assert result["exit_code"] == 124


def test_new_container_has_no_network(monkeypatch):
    manager = bare_manager()
    created = {}

    class FakeNotFound(Exception):
        pass

    class Containers:
        def get(self, _name):
            raise FakeNotFound

        def create(self, **kwargs):
            created.update(kwargs)
            return SimpleNamespace(id="container-id", start=lambda: None)

    manager.client = SimpleNamespace(containers=Containers())
    monkeypatch.setattr(sandbox_module, "NotFound", FakeNotFound)

    manager._create_container("sandbox", "volume", None)

    assert created["network_mode"] == "none"
    assert created["read_only"] is True
    assert created["cap_drop"] == ["ALL"]


@pytest.mark.asyncio
async def test_package_install_temporarily_connects_network_and_persists_in_workspace():
    manager = bare_manager()
    manager._exec = AsyncMock(return_value={"stdout": "ok", "stderr": "", "exit_code": 0})
    manager._connect_install_network = AsyncMock()
    manager._disconnect_install_network = AsyncMock()
    sandbox = SimpleNamespace(id=uuid4(), user_id=uuid4(), container_name="sandbox")

    result = await manager.install_packages(sandbox, ["httpx>=0.28"], manager="pip")

    assert result.exit_code == 0
    manager._connect_install_network.assert_awaited_once_with(sandbox)
    manager._disconnect_install_network.assert_awaited_once_with(sandbox)
    install_command = manager._exec.await_args_list[1].args[1]
    assert "--target /workspace/.quip/deps/python" in install_command


@pytest.mark.asyncio
async def test_execution_uses_unique_script_and_removes_it():
    manager = bare_manager()
    manager._write_file_raw = AsyncMock()
    manager._list_raw = AsyncMock(side_effect=[{"_run-old.py"}, {"_run-old.py", "report.csv"}])
    manager._exec = AsyncMock(
        side_effect=[
            {"stdout": "done", "stderr": "", "exit_code": 0},
            {"stdout": "", "stderr": "", "exit_code": 0},
        ]
    )
    sandbox = SimpleNamespace(id=uuid4(), user_id=uuid4(), container_name="sandbox")

    result = await manager.execute(sandbox, "chat", "print('done')", "python")

    script_path = manager._write_file_raw.await_args.args[1]
    assert script_path.startswith("/workspace/chat/_run-")
    assert script_path.endswith(".py")
    assert result.files_created == ["report.csv"]
    assert manager._exec.await_args_list[-1].args[1].startswith("rm -f ")


@pytest.mark.asyncio
async def test_failed_chat_directory_is_not_cached():
    manager = bare_manager()
    manager._chat_dirs_ready = set()
    manager._exec = AsyncMock(return_value={"stdout": "", "stderr": "permission denied", "exit_code": 1})
    sandbox = SimpleNamespace(container_id="container-id")

    with pytest.raises(RuntimeError, match="permission denied"):
        await manager.ensure_chat_dir(sandbox, "chat-id")

    assert manager._chat_dirs_ready == set()


@pytest.mark.asyncio
async def test_file_listing_parses_size_and_quotes_user_path():
    manager = bare_manager()
    manager._exec = AsyncMock(
        return_value={
            "stdout": "36 f result.txt\n0 d nested\n",
            "stderr": "",
            "exit_code": 0,
        }
    )
    sandbox = SimpleNamespace()

    files = await manager.list_files(sandbox, "chat-id", "folder with spaces")

    assert [(item.name, item.size, item.is_dir) for item in files] == [
        ("result.txt", 36, False),
        ("nested", 0, True),
    ]
    command = manager._exec.await_args.args[1]
    assert "cd '/workspace/chat-id/folder with spaces'" in command


def test_package_options_are_rejected():
    with pytest.raises(ValueError, match="Invalid package"):
        SandboxManager._validated_packages(["--index-url=https://example.invalid"])


@pytest.mark.asyncio
async def test_first_sandbox_startup_does_not_hold_sqlite_writer(tmp_path, monkeypatch):
    db_path = tmp_path / "sandbox.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    manager = bare_manager()
    monkeypatch.setattr(sandbox_module, "QUIP_HOST_SANDBOX_DIR", "")

    def create_container(*_args):
        # External container startup must leave unrelated SQLite writes free.
        with sqlite3.connect(db_path, timeout=0.1) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        return "mock-container-id"

    monkeypatch.setattr(manager, "_create_container", create_container)
    try:
        async with sessions() as db:
            user = User(email="sandbox-writer@test.dev", username="sandbox-writer", name="Writer")
            db.add(user)
            await db.commit()
            sandbox = await manager.get_or_create(user.id, db)
            assert sandbox.status == "running"
            assert sandbox.container_id == "mock-container-id"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parallel_sandbox_requests_share_one_startup(tmp_path, monkeypatch):
    db_path = tmp_path / "parallel-sandbox.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        user = User(email="parallel@test.dev", username="parallel", name="Parallel")
        db.add(user)
        await db.commit()
        user_id = user.id

    manager = bare_manager()
    monkeypatch.setattr(sandbox_module, "QUIP_HOST_SANDBOX_DIR", "")
    started = threading.Event()
    release = threading.Event()
    startup_count = 0

    def create_container(*_args):
        nonlocal startup_count
        startup_count += 1
        started.set()
        assert release.wait(timeout=5)
        return "shared-container-id"

    def get_container(sandbox):
        if sandbox.container_id is None:
            create_container()
        return SimpleNamespace(status="running")

    monkeypatch.setattr(manager, "_create_container", create_container)
    monkeypatch.setattr(manager, "_get_container", get_container)

    async def get_sandbox():
        async with sessions() as db:
            return await manager.get_or_create(user_id, db)

    try:
        first = asyncio.create_task(get_sandbox())
        assert await asyncio.to_thread(started.wait, 5)
        second = asyncio.create_task(get_sandbox())
        await asyncio.sleep(0.2)
        assert startup_count == 1
        release.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result.container_id == second_result.container_id == "shared-container-id"
    finally:
        release.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_sandbox_creation_is_recovered(db_session, monkeypatch):
    user = User(email="stale@test.dev", username="stale", name="Stale")
    db_session.add(user)
    await db_session.flush()
    sandbox = Sandbox(
        user_id=user.id,
        container_name=f"quip-sandbox-{user.id.hex}",
        volume_name=f"quip-sandbox-vol-{user.id.hex}",
        status="creating",
        last_active_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db_session.add(sandbox)
    await db_session.commit()

    manager = bare_manager()
    monkeypatch.setattr(manager, "_create_container", lambda *_args: "recovered-container")
    recovered = await manager.get_or_create(user.id, db_session)

    assert recovered.status == "running"
    assert recovered.container_id == "recovered-container"


@pytest.mark.asyncio
async def test_simultaneous_first_sandbox_requests_share_reservation(tmp_path, monkeypatch):
    db_path = tmp_path / "first-sandbox.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        user = User(email="first@test.dev", username="first", name="First")
        db.add(user)
        await db.commit()
        user_id = user.id

    manager = bare_manager()
    monkeypatch.setattr(sandbox_module, "QUIP_HOST_SANDBOX_DIR", "")
    starts = 0

    def create_container(*_args):
        nonlocal starts
        starts += 1
        return "first-container"

    monkeypatch.setattr(manager, "_create_container", create_container)
    monkeypatch.setattr(manager, "_get_container", lambda _sandbox: SimpleNamespace(status="running"))
    original_execute = AsyncSession.execute
    reads = 0
    both_read = asyncio.Event()

    async def synchronized_execute(self, statement, *args, **kwargs):
        nonlocal reads
        result = await original_execute(self, statement, *args, **kwargs)
        if "FROM sandboxes" in str(statement) and "sandboxes.user_id" in str(statement) and reads < 2:
            reads += 1
            if reads == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), timeout=5)
        return result

    monkeypatch.setattr(AsyncSession, "execute", synchronized_execute)

    async def get_sandbox():
        async with sessions() as db:
            return await manager.get_or_create(user_id, db)

    try:
        first, second = await asyncio.wait_for(
            asyncio.gather(get_sandbox(), get_sandbox()), timeout=10
        )
        assert first.id == second.id
        assert starts == 1
    finally:
        await engine.dispose()
