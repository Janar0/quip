import pytest
from httpx import AsyncClient, ASGITransport

from quip.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_and_login(client):
    # Register
    res = await client.post("/api/auth/register", json={
        "email": "test@quip.dev",
        "username": "testuser",
        "name": "Test User",
        "password": "password123",
    })
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data

    # Login
    res = await client.post("/api/auth/login", json={
        "email": "test@quip.dev",
        "password": "password123",
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data

    # Me
    res = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {data['access_token']}"
    })
    assert res.status_code == 200
    me = res.json()
    assert me["email"] == "test@quip.dev"
    assert me["username"] == "testuser"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await client.post("/api/auth/register", json={
        "email": "dup@quip.dev", "username": "user1", "name": "U1", "password": "pass123",
    })
    res = await client.post("/api/auth/register", json={
        "email": "dup@quip.dev", "username": "user2", "name": "U2", "password": "pass123",
    })
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/auth/register", json={
        "email": "wrong@quip.dev", "username": "wronguser", "name": "W", "password": "correct",
    })
    res = await client.post("/api/auth/login", json={
        "email": "wrong@quip.dev", "password": "incorrect",
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_first_user_is_admin(client):
    res = await client.post("/api/auth/register", json={
        "email": "first@quip.dev", "username": "firstuser", "name": "First", "password": "pass123",
    })
    data = res.json()
    res = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {data['access_token']}"
    })
    me = res.json()
    assert me["role"] == "admin"
