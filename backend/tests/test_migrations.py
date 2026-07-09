import asyncio
import uuid

from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from quip.migrations.runner import _alembic_config, upgrade_schema


async def _schema_snapshot(database_url: str):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables, chat_columns, file_columns = await connection.run_sync(
                lambda sync_connection: (
                    set(inspect(sync_connection).get_table_names()),
                    {column["name"] for column in inspect(sync_connection).get_columns("chats")},
                    {column["name"] for column in inspect(sync_connection).get_columns("files")},
                )
            )
            revision = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
            return tables, chat_columns, file_columns, revision
    finally:
        await engine.dispose()


def test_fresh_database_migrates_to_workspace_head(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'migrations.db'}"

    upgrade_schema(database_url)
    # A second boot must be an idempotent no-op.
    upgrade_schema(database_url)

    tables, chat_columns, file_columns, revision = asyncio.run(
        _schema_snapshot(database_url)
    )
    assert {"workspaces", "workspace_members", "chat_runs"}.issubset(tables)
    assert "workspace_id" in chat_columns
    assert "workspace_id" in file_columns
    assert revision == "0003"


async def _seed_unversioned_baseline(database_url: str):
    engine = create_async_engine(database_url)
    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    file_id = uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, username, name, role) "
                    "VALUES (:id, :email, :username, :name, :role)"
                ),
                {
                    "id": user_id.hex,
                    "email": "legacy@quip.dev",
                    "username": "legacy",
                    "name": "Legacy User",
                    "role": "admin",
                },
            )
            await connection.execute(
                text("INSERT INTO chats (id, user_id, title) VALUES (:id, :user_id, :title)"),
                {"id": chat_id.hex, "user_id": user_id.hex, "title": "Legacy chat"},
            )
            await connection.execute(
                text(
                    "INSERT INTO files (id, user_id, filename, storage_path) "
                    "VALUES (:id, :user_id, :filename, :storage_path)"
                ),
                {
                    "id": file_id.hex,
                    "user_id": user_id.hex,
                    "filename": "legacy.txt",
                    "storage_path": "legacy/file.txt",
                },
            )
            await connection.execute(text("DROP TABLE alembic_version"))
    finally:
        await engine.dispose()


def test_unversioned_database_is_stamped_and_backfilled(tmp_path, monkeypatch):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(_alembic_config(database_url), "0001")
    asyncio.run(_seed_unversioned_baseline(database_url))

    upgrade_schema(database_url)

    async def verify():
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                workspace_count = (
                    await connection.execute(text("SELECT count(*) FROM workspaces"))
                ).scalar_one()
                chat_workspace = (
                    await connection.execute(text("SELECT workspace_id FROM chats"))
                ).scalar_one()
                file_workspace = (
                    await connection.execute(text("SELECT workspace_id FROM files"))
                ).scalar_one()
                revision = (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one()
                return workspace_count, chat_workspace, file_workspace, revision
        finally:
            await engine.dispose()

    workspace_count, chat_workspace, file_workspace, revision = asyncio.run(verify())
    assert workspace_count == 1
    assert chat_workspace
    assert file_workspace == chat_workspace
    assert revision == "0003"
