import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("EXECUTOR_TOKEN", "test-executor-token-long-enough")
os.environ.setdefault("QUIP_HOST_SANDBOX_DIR", "/tmp/quip-executor-tests")

from quip import executor_app


def test_workspace_paths_cannot_escape():
    assert executor_app._validate_workspace_path("/workspace/chat/file.txt") == "/workspace/chat/file.txt"
    with pytest.raises(HTTPException, match="Path escapes workspace"):
        executor_app._validate_workspace_path("/workspace/../../etc/shadow")


def test_container_identity_is_fixed_to_user_key():
    executor_app._validate_name("quip-sandbox-deadbeef", "deadbeef")
    with pytest.raises(HTTPException, match="Invalid sandbox identity"):
        executor_app._validate_name("postgres", "deadbeef")
    with pytest.raises(HTTPException, match="Invalid sandbox identity"):
        executor_app._validate_name("quip-sandbox-deadbeef", "cafebabe")


def test_unlabelled_host_container_is_rejected(monkeypatch):
    container = SimpleNamespace(
        id="host-container",
        name="quip-sandbox-deadbeef",
        attrs={"Config": {"Labels": {}}, "NetworkSettings": {"Networks": {}}},
        reload=lambda: None,
    )
    monkeypatch.setattr(
        executor_app,
        "client",
        SimpleNamespace(containers=SimpleNamespace(get=lambda _reference: container)),
    )

    with pytest.raises(HTTPException, match="not managed"):
        executor_app._managed_container("host-container")


def test_created_container_has_fixed_image_mount_and_isolation(monkeypatch, tmp_path):
    captured = {}
    fake_container = SimpleNamespace(id="sandbox-id", start=lambda: None)
    fake_client = SimpleNamespace(
        containers=SimpleNamespace(
            create=lambda **kwargs: (captured.update(kwargs) or fake_container)
        )
    )
    monkeypatch.setattr(executor_app, "client", fake_client)
    monkeypatch.setattr(executor_app, "MOUNTED_SANDBOX_DIR", tmp_path)
    monkeypatch.setattr(executor_app, "HOST_SANDBOX_DIR", "/srv/quip-sandbox")

    executor_app._create_container("quip-sandbox-deadbeef", "deadbeef")

    assert captured["image"] == executor_app.SANDBOX_IMAGE
    assert captured["volumes"] == {
        "/srv/quip-sandbox/deadbeef": {"bind": "/workspace", "mode": "rw"}
    }
    assert captured["network_mode"] == "none"
    assert captured["read_only"] is True
    assert captured["cap_drop"] == ["ALL"]
    assert captured["labels"][executor_app.MANAGED_LABEL] == "true"


def test_install_rejects_package_options():
    with pytest.raises(HTTPException, match="Invalid package specifier"):
        executor_app._validated_packages(["--index-url=https://example.invalid"])


def test_existing_unmanaged_container_is_never_deleted(monkeypatch):
    removed = False

    def remove(*, force):
        nonlocal removed
        removed = force

    container = SimpleNamespace(
        id="host-container",
        name="quip-sandbox-deadbeef",
        status="running",
        attrs={
            "Config": {"Labels": {}},
            "HostConfig": {"NetworkMode": "bridge"},
        },
        reload=lambda: None,
        remove=remove,
    )
    monkeypatch.setattr(
        executor_app,
        "client",
        SimpleNamespace(containers=SimpleNamespace(get=lambda _reference: container)),
    )

    with pytest.raises(HTTPException, match="Conflicting container"):
        executor_app.ensure_container(
            executor_app.ContainerRequest(name="quip-sandbox-deadbeef", user_key="deadbeef")
        )
    assert removed is False
