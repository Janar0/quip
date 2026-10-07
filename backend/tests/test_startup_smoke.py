"""Exercise real startup and cookie authentication across fresh processes."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PROBE = r"""
import asyncio
import json
import logging
import os
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from quip.main import app

logging.disable(logging.CRITICAL)
state_file = Path(os.environ["SMOKE_STATE_FILE"])

async def probe():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke") as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 200
            if state_file.exists():
                for cookie in json.loads(state_file.read_text()):
                    client.cookies.set(**cookie)
                assert (await client.get("/api/auth/setup")).json()["required"] is False
            else:
                registration = {
                    "email": "smoke-owner@example.invalid", "username": "smoke-owner",
                    "name": "Smoke Owner", "password": "smoke-password-123",
                }
                assert (await client.post("/api/auth/register", json=registration)).status_code == 403
                registration["bootstrap_token"] = os.environ["BOOTSTRAP_TOKEN"]
                registered = await client.post("/api/auth/register", json=registration)
                assert registered.status_code == 201
                assert all("HttpOnly" in value for value in registered.headers.get_list("set-cookie"))
                login = await client.post("/api/auth/login", json={
                    "email": registration["email"], "password": registration["password"],
                })
                assert login.status_code == 200
            me = await client.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["role"] == "admin"
            client.cookies.delete("quip_access")
            refresh = await client.post("/api/auth/refresh", json={})
            assert refresh.status_code == 200
            assert refresh.json() == {"status": "ok"}
            assert (await client.get("/api/auth/me")).status_code == 200
            state_file.write_text(json.dumps([
                {"name": cookie.name, "value": cookie.value,
                 "domain": cookie.domain, "path": cookie.path}
                for cookie in client.cookies.jar
            ]))
            state_file.chmod(0o600)
    print("startup, readiness and cookie authentication passed")

asyncio.run(probe())
"""


def test_example_configuration_starts_and_preserves_sessions_after_restart(tmp_path):
    environment = {
        **os.environ,
        **{key: value for key, value in dotenv_values(ROOT / ".env.example").items() if value is not None},
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'smoke.db'}",
        "JWT_SECRET": "",
        "JWT_SECRET_FILE": str(tmp_path / ".jwt_secret"),
        "BOOTSTRAP_TOKEN": "smoke-bootstrap-token",
        "ADMIN_EMAIL": "smoke-owner@example.invalid",
        "SANDBOX_EXECUTOR_URL": "",
        "TELEGRAM_BOT_TOKEN": "",
        "AUTO_MIGRATE": "true",
        "SMOKE_STATE_FILE": str(tmp_path / "session.json"),
    }
    first_secret = None
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=ROOT / "backend",
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "startup, readiness and cookie authentication passed" in result.stdout
        secret = (tmp_path / ".jwt_secret").read_bytes()
        if first_secret is None:
            first_secret = secret
        else:
            assert secret == first_secret
