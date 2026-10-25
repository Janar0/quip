import hashlib
import hmac

import httpx
import pytest

import quip.routers.roki as roki
from quip.models.user import User
from quip.services.auth import create_access_token

SECRET = "k" * 32


def test_signature_vector_shared_with_roki():
    # Roki's tests/test_quip_identity.py checks the same vector.
    headers = roki.sign(
        SECRET.encode(), "GET", "/api/presence?x=1", "0b6c1e5e-8f0e-4a51-9d1c-2f3a4b5c6d7e", False, now=1700000000
    )
    assert headers["X-Roki-Signature"] == "ed176a9d1d0ab4c958887f3efd458b8cf049946d6ec3af26a6f560ce177a5aef"


@pytest.fixture
def upstream(monkeypatch):
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = await request.aread()
        if request.url.path == "/api/broken":
            raise httpx.ConnectError("down")
        if request.url.path == "/api/tasks/t1/screenshot":
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304, headers={"ETag": '"v1"'})
            return httpx.Response(200, content=b"PNG", headers={"Content-Type": "image/png", "ETag": '"v1"'})
        return httpx.Response(
            200,
            json={"path": request.url.path, "query": request.url.query.decode(), "body": body.decode()},
            headers={"X-Internal": "hidden"},
        )

    monkeypatch.setenv("ROKI_IDENTITY_SECRET", SECRET)
    monkeypatch.setenv("ROKI_URL", "http://roki.test")
    monkeypatch.setattr(roki, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


async def make_user(db_session, role="user", active=True):
    user = User(email=f"{role}{active}@quip.dev", username=f"{role}{active}", name=role, role=role, is_active=active)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, {"Authorization": f"Bearer {create_access_token(str(user.id), role)}"}


def check_signature(request: httpx.Request, user: User, admin: bool):
    target = request.url.raw_path.decode()
    stamp = request.headers["x-roki-time"]
    flag = "1" if admin else "0"
    message = f"{stamp}\n{user.id}\n{flag}\n{request.method}\n{target}".encode()
    assert request.headers["x-roki-user"] == str(user.id)
    assert request.headers["x-roki-admin"] == flag
    assert request.headers["x-roki-signature"] == hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()


async def test_requires_quip_login(client, upstream):
    assert (await client.get("/api/roki/presence")).status_code == 401
    assert upstream == []


async def test_blocked_and_pending_users_rejected(client, db_session, upstream):
    _, blocked = await make_user(db_session, active=False)
    _, pending = await make_user(db_session, role="pending")
    assert (await client.get("/api/roki/presence", headers=blocked)).status_code == 401
    assert (await client.get("/api/roki/presence", headers=pending)).status_code == 403
    assert upstream == []


async def test_not_configured_is_hidden(client, db_session, upstream, monkeypatch):
    monkeypatch.delenv("ROKI_URL")
    _, headers = await make_user(db_session)
    assert (await client.get("/api/roki/presence", headers=headers)).status_code == 404
    features = (await client.get("/api/models/features", headers=headers)).json()
    assert features["roki_enabled"] is False


async def test_forwards_signed_identity(client, db_session, upstream):
    user, headers = await make_user(db_session)
    assert (await client.get("/api/models/features", headers=headers)).json()["roki_enabled"] is True
    res = await client.get("/api/roki/harness?query=calc", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"path": "/api/harness", "query": "query=calc", "body": ""}
    assert "x-internal" not in res.headers
    check_signature(upstream[-1], user, False)
    assert "authorization" not in upstream[-1].headers
    assert "cookie" not in upstream[-1].headers

    res = await client.post("/api/roki/conversation/messages", headers=headers, json={"key": "1", "content": "привет"})
    assert res.json()["body"] == '{"key":"1","content":"привет"}'
    check_signature(upstream[-1], user, False)


async def test_admin_paths_need_quip_admin(client, db_session, upstream):
    _, user_headers = await make_user(db_session)
    admin, admin_headers = await make_user(db_session, role="admin")
    assert (await client.get("/api/roki/admin/summary", headers=user_headers)).status_code == 403
    assert len(upstream) == 0
    assert (await client.get("/api/roki/admin/summary", headers=admin_headers)).status_code == 200
    check_signature(upstream[-1], admin, True)


async def test_frames_keep_etag(client, db_session, upstream):
    _, headers = await make_user(db_session)
    first = await client.get("/api/roki/tasks/t1/screenshot", headers=headers)
    assert first.content == b"PNG" and first.headers["etag"] == '"v1"'
    again = await client.get("/api/roki/tasks/t1/screenshot", headers={**headers, "If-None-Match": '"v1"'})
    assert again.status_code == 304


async def test_bad_paths_and_unavailable_roki(client, db_session, upstream):
    _, headers = await make_user(db_session)
    assert (await client.get("/api/roki/a//b", headers=headers)).status_code == 404
    assert (await client.get("/api/roki/a/%2e%2e/admin/summary", headers=headers)).status_code == 404
    assert (await client.get("/api/roki/broken", headers=headers)).status_code == 502


async def test_attachment_upload_keeps_filename_and_body(client, db_session, upstream):
    _, headers = await make_user(db_session)
    res = await client.post(
        "/api/roki/conversation/attachments",
        headers={**headers, "Content-Type": "application/octet-stream", "X-Roki-Filename": "%D0%BE%D1%82%D1%87%D1%91%D1%82.csv"},
        content=b"a;b\n1;2\n",
    )
    assert res.json()["body"] == "a;b\n1;2\n"
    assert upstream[-1].headers["x-roki-filename"] == "%D0%BE%D1%82%D1%87%D1%91%D1%82.csv"
    assert upstream[-1].headers["content-type"] == "application/octet-stream"
