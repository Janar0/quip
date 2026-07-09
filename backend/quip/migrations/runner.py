"""Safe Alembic entrypoint for fresh and pre-Alembic QUIP databases."""

import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
SCHEMA_REVISION = "0003"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "quip" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
    finally:
        await engine.dispose()


def upgrade_schema(database_url: str | None = None) -> None:
    database_url = database_url or os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///quip.db",
    )
    os.environ["DATABASE_URL"] = database_url
    tables = asyncio.run(_table_names(database_url))
    config = _alembic_config(database_url)

    if "alembic_version" not in tables and "users" in tables:
        # The old application created its schema at runtime. Treat that known
        # shape as baseline, then run every explicit migration after it.
        command.stamp(config, "0001")
    elif "alembic_version" not in tables and tables:
        raise RuntimeError(
            "Database is not empty and does not look like a QUIP schema; refusing automatic migration"
        )

    command.upgrade(config, "head")


if __name__ == "__main__":
    upgrade_schema()
