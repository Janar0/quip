"""Exercise startup configuration in isolated processes and temporary data directories."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PLACEHOLDER = "dev-secret-change-in-production"
CONFIGURED_KEY = "configured-test-key-at-least-32-bytes-long"
IMPORT_SECRET = "from quip.services.auth import JWT_SECRET; print(JWT_SECRET)"


def startup_env(secret_file, configured=None):
    env = os.environ.copy()
    env.pop("JWT_SECRET", None)
    env["JWT_SECRET_FILE"] = str(secret_file)
    if configured is not None:
        env["JWT_SECRET"] = configured
    return env


def startup(secret_file, configured=None):
    return subprocess.run(
        [sys.executable, "-c", IMPORT_SECRET],
        cwd=BACKEND,
        env=startup_env(secret_file, configured),
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize("configured", [None, "", "   ", PLACEHOLDER])
def test_unconfigured_startup_creates_private_persistent_secret(tmp_path, configured):
    secret_file = tmp_path / "data" / ".jwt_secret"
    first = startup(secret_file, configured)
    assert first.returncode == 0, first.stderr
    secret = first.stdout.strip()
    assert len(secret.encode("utf-8")) >= 32
    assert secret != PLACEHOLDER
    assert secret_file.read_text() == secret
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    second = startup(secret_file, configured)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == secret


def test_existing_deployed_secret_is_reused_without_rewriting(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    existing = "a" * 64 + "\n"
    secret_file.write_text(existing)
    first = startup(secret_file)
    second = startup(secret_file, PLACEHOLDER)
    assert first.returncode == second.returncode == 0
    assert first.stdout.strip() == second.stdout.strip() == "a" * 64
    assert secret_file.read_text() == existing


def test_configured_key_takes_priority_and_does_not_touch_secret_file(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    secret_file.write_bytes(b"corrupt")
    result = startup(secret_file, CONFIGURED_KEY)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == CONFIGURED_KEY
    assert secret_file.read_bytes() == b"corrupt"


@pytest.mark.parametrize("configured", ["short", "a" * 31, "\u043a" * 15])
def test_explicit_short_key_fails_configuration(tmp_path, configured):
    secret_file = tmp_path / ".jwt_secret"
    result = startup(secret_file, configured)
    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr
    assert "32 UTF-8 bytes" in result.stderr
    assert not secret_file.exists()
    assert configured not in result.stderr


def test_configured_key_minimum_is_utf8_bytes(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    result = startup(secret_file, "\u043a" * 16)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "\u043a" * 16
    assert not secret_file.exists()


@pytest.mark.parametrize("contents", [b"", b"short", b" " * 64, PLACEHOLDER.encode(), b"\xff" * 64])
def test_corrupt_existing_file_fails_without_replacing_it(tmp_path, contents):
    secret_file = tmp_path / ".jwt_secret"
    secret_file.write_bytes(contents)
    result = startup(secret_file)
    assert result.returncode != 0
    assert "JWT secret file" in result.stderr
    assert secret_file.read_bytes() == contents


def test_concurrent_first_startups_share_one_complete_secret(tmp_path):
    secret_file = tmp_path / "data" / ".jwt_secret"
    code = "import sys; sys.stdin.read(1); " + IMPORT_SECRET
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=BACKEND,
            env=startup_env(secret_file),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(12)
    ]
    try:
        for process in processes:
            process.stdin.write("x")
            process.stdin.flush()
        results = [process.communicate(timeout=30) for process in processes]
        assert all(process.returncode == 0 for process in processes), results
        secrets = {stdout.strip() for stdout, _ in results}
        assert len(secrets) == 1
        secret = secrets.pop()
        assert len(secret.encode("utf-8")) >= 32
        assert secret != PLACEHOLDER
        assert secret_file.read_text() == secret
        assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
        assert list(secret_file.parent.iterdir()) == [secret_file]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()


def test_entrypoint_rejects_weak_configuration_before_starting_services(tmp_path):
    """Run the real entrypoint with inert migrations and supervisor stand-ins."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "quip.migrations.runner" ]; then exit 0; fi\n'
        f'exec "{sys.executable}" "$@"\n'
    )
    python.chmod(0o755)
    supervisor = bin_dir / "supervisord"
    supervisor.write_text("#!/bin/sh\nexit 0\n")
    supervisor.chmod(0o755)
    env = startup_env(tmp_path / ".jwt_secret", "short")
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["sh", str(BACKEND.parent / "entrypoint.sh")],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr
    assert "32 UTF-8 bytes" in result.stderr
