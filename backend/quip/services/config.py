"""Config service — stores settings in DB, cached in memory."""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from quip.database import async_session
from quip.models.config import Config

# In-memory cache (loaded from DB on startup)
_settings: dict[str, str] = {}


def get_setting(key: str, default: str = "") -> str:
    """Get a setting value. Priority: memory > env > default."""
    return _settings.get(key) or os.getenv(key.upper(), default)


def set_setting(key: str, value: str) -> None:
    """Set a setting in memory (call save_settings() to persist)."""
    _settings[key] = value


def get_all_settings() -> dict[str, str]:
    return dict(_settings)


async def load_settings():
    """Load settings from DB into memory. Call once at startup."""
    async with async_session() as db:
        result = await db.execute(select(Config).where(Config.id == 1))
        row = result.scalar_one_or_none()
        if row and isinstance(row.data, dict):
            _settings.update(row.data)

    # Env vars can bootstrap settings not yet in DB
    env_keys = ["openrouter_api_key"]
    for key in env_keys:
        val = os.getenv(key.upper(), "")
        if val and key not in _settings:
            _settings[key] = val


async def save_settings():
    """Persist current in-memory settings to DB."""
    async with async_session() as db:
        result = await db.execute(select(Config).where(Config.id == 1))
        row = result.scalar_one_or_none()
        if row:
            row.data = dict(_settings)
            flag_modified(row, "data")
            row.version = (row.version or 0) + 1
        else:
            row = Config(id=1, data=dict(_settings), version=1)
            db.add(row)
        await db.commit()
