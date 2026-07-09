import os

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///quip.db")

_url = make_url(DATABASE_URL)
_engine_options = {"echo": False, "pool_pre_ping": True}
if _url.get_backend_name() == "sqlite":
    _engine_options["connect_args"] = {"timeout": 30}

engine = create_async_engine(DATABASE_URL, **_engine_options)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if _url.get_backend_name() == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session
