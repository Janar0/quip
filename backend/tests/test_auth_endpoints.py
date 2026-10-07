import pytest
from httpx import ASGITransport, AsyncClient

from quip.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "wrong-bootstrap-token"])
async def test_configured_admin_email_cannot_bypass_bootstrap_token(client, monkeypatch, token):
    from quip.routers import auth

    monkeypatch.setattr(auth, "ADMIN_EMAIL", "owner@example.test")
    setup = await client.get("/api/auth/setup")
    assert setup.json() == {"required": True, "admin_email_configured": True}
    data = {
        "email": "owner@example.test",
        "username": "owner",
        "name": "Owner",
        "password": "password123",
    }
    if token is not None:
        data["bootstrap_token"] = token
    denied = await client.post("/api/auth/register", json=data)
    assert denied.status_code == 403
    assert (await client.get("/api/auth/setup")).json()["required"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["owner@example.test", "different@example.test"])
async def test_valid_bootstrap_token_grants_admin_independent_of_configured_email(client, monkeypatch, email):
    from quip.routers import auth

    monkeypatch.setattr(auth, "ADMIN_EMAIL", "owner@example.test")
    claimed = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": "owner",
            "name": "Owner",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    assert claimed.status_code == 201
    assert (await client.get("/api/auth/me")).json()["role"] == "admin"
    assert (await client.get("/api/auth/setup")).json()["required"] is False


@pytest.mark.asyncio
async def test_registration_after_bootstrap_stays_pending_even_for_configured_email(client, monkeypatch):
    from quip.routers import auth

    monkeypatch.setattr(auth, "ADMIN_EMAIL", "later@example.test")
    await client.post(
        "/api/auth/register",
        json={
            "email": "owner@example.test",
            "username": "owner",
            "name": "Owner",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    pending = await client.post(
        "/api/auth/register",
        json={
            "email": "later@example.test",
            "username": "later",
            "name": "Later",
            "password": "password123",
        },
    )
    assert pending.status_code == 201
    login = await client.post("/api/auth/login", json={"email": "later@example.test", "password": "password123"})
    assert login.status_code == 403
    assert login.json()["detail"] == "Account pending approval"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_and_login(client):
    # Register
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "test@quip.dev",
            "username": "testuser",
            "name": "Test User",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    cookies = res.headers.get_list("set-cookie")
    assert any("quip_access=" in cookie and "HttpOnly" in cookie for cookie in cookies)
    assert any("quip_refresh=" in cookie and "HttpOnly" in cookie for cookie in cookies)

    # Login
    res = await client.post(
        "/api/auth/login",
        json={
            "email": "test@quip.dev",
            "password": "password123",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data

    # Me
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert res.status_code == 200
    me = res.json()
    assert me["email"] == "test@quip.dev"
    assert me["username"] == "testuser"


@pytest.mark.asyncio
async def test_first_admin_requires_one_time_bootstrap_token(client):
    setup = await client.get("/api/auth/setup")
    assert setup.status_code == 200
    assert setup.json()["required"] is True

    denied = await client.post(
        "/api/auth/register",
        json={
            "email": "missing-token@quip.dev",
            "username": "missing-token",
            "name": "Missing Token",
            "password": "password123",
        },
    )
    assert denied.status_code == 403

    claimed = await client.post(
        "/api/auth/register",
        json={
            "email": "owner@quip.dev",
            "username": "owner",
            "name": "Owner",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    assert claimed.status_code == 201
    assert (await client.get("/api/auth/setup")).json()["required"] is False


@pytest.mark.asyncio
async def test_cookie_session_refresh_and_logout(client):
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "cookie@quip.dev",
            "username": "cookieuser",
            "name": "Cookie User",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    assert res.status_code == 201
    register_tokens = res.json()

    # No Authorization header: the HttpOnly access cookie authenticates the request.
    res = await client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json()["email"] == "cookie@quip.dev"

    client.cookies.delete("quip_access")
    res = await client.post("/api/auth/refresh", json={})
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert "access_token" not in res.text
    assert "refresh_token" not in res.text
    assert client.cookies.get("quip_access")

    # Explicit-token clients retain the bearer-token rotation contract.
    res = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": register_tokens["refresh_token"]},
    )
    assert res.status_code == 200
    assert "access_token" in res.json()
    assert "refresh_token" in res.json()

    res = await client.post("/api/auth/logout")
    assert res.status_code == 204
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await client.post(
        "/api/auth/register",
        json={
            "email": "dup@quip.dev",
            "username": "user1",
            "name": "U1",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "dup@quip.dev",
            "username": "user2",
            "name": "U2",
            "password": "password123",
        },
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_registration_rejects_case_insensitive_username_duplicate(client):
    await client.post(
        "/api/auth/register",
        json={
            "email": "first-name@quip.dev",
            "username": "SameName",
            "name": "First",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "second-name@quip.dev",
            "username": "samename",
            "name": "Second",
            "password": "password123",
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_registration_rejects_password_beyond_bcrypt_limit(client):
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "long-password@quip.dev",
            "username": "long-password",
            "name": "Long Password",
            "password": "x" * 73,
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post(
        "/api/auth/register",
        json={
            "email": "wrong@quip.dev",
            "username": "wronguser",
            "name": "W",
            "password": "correct-password",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    res = await client.post(
        "/api/auth/login",
        json={
            "email": "wrong@quip.dev",
            "password": "incorrect-password",
        },
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_first_user_is_admin(client):
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "first@quip.dev",
            "username": "firstuser",
            "name": "First",
            "password": "password123",
            "bootstrap_token": "test-bootstrap-token",
        },
    )
    data = res.json()
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    me = res.json()
    assert me["role"] == "admin"
