from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import quip.services.sandbox as sandbox_module
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
