import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["JWT_SECRET"] = "test-secret-key"

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from quip.database import Base, get_db
from quip.main import app
import quip.models  # noqa: F401


@pytest.fixture(scope="function", autouse=True)
async def setup_db():
    """Create fresh tables for each test."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    """Async HTTP client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(client):
    """Register a test user and return Bearer auth headers."""
    res = await client.post("/api/auth/register", json={
        "email": "test@quip.dev",
        "username": "testuser",
        "name": "Test User",
        "password": "password123",
    })
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
async def db_session():
    """Get a DB session from the test-overridden dependency."""
    gen = app.dependency_overrides[get_db]()
    session = await anext(gen)
    yield session
    await session.close()


@pytest.fixture
def tmp_upload_dir(tmp_path):
    """Redirect file uploads to a temp directory."""
    import quip.routers.files as files_mod
    original = files_mod.UPLOAD_DIR
    files_mod.UPLOAD_DIR = tmp_path
    yield tmp_path
    files_mod.UPLOAD_DIR = original


@pytest.fixture(autouse=True)
def _reset_settings():
    """Reset in-memory config settings between tests."""
    from quip.services import config
    saved = dict(config._settings)
    yield
    config._settings.clear()
    config._settings.update(saved)
