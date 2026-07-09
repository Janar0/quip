"""Add workspaces, durable chat runs, and backfill legacy ownership.

Revision ID: 0002
Revises: 0001
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _index_names(bind, table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # Old deployments used best-effort ALTER statements at startup. Repair any
    # database that was stamped at the baseline before adding the new domain.
    skill_columns = _column_names(bind, "skill")
    with op.batch_alter_table("skill") as batch:
        if "settings_schema" not in skill_columns:
            batch.add_column(sa.Column("settings_schema", sa.JSON()))
        if "settings" not in skill_columns:
            batch.add_column(sa.Column("settings", sa.JSON()))

    chunk_columns = _column_names(bind, "document_chunks")
    with op.batch_alter_table("document_chunks") as batch:
        if "chunk_metadata" not in chunk_columns:
            batch.add_column(sa.Column("chunk_metadata", sa.JSON()))
        if "content_hash" not in chunk_columns:
            batch.add_column(sa.Column("content_hash", sa.String(64)))
    if "ix_document_chunks_content_hash" not in _index_names(bind, "document_chunks"):
        op.create_index(
            "ix_document_chunks_content_hash",
            "document_chunks",
            ["content_hash"],
        )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("instructions", sa.Text()),
        sa.Column("default_model", sa.String(255)),
        sa.Column("is_personal", sa.Boolean(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )

    with op.batch_alter_table("chats") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_chats_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_chats_workspace_id", ["workspace_id"])
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_files_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_files_workspace_id", ["workspace_id"])

    op.create_table(
        "chat_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("run_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_runs_chat_id", "chat_runs", ["chat_id"])
    op.create_index("ix_chat_runs_user_id", "chat_runs", ["user_id"])
    op.create_index("ix_chat_runs_assistant_message_id", "chat_runs", ["assistant_message_id"])
    op.create_index("ix_chat_runs_status", "chat_runs", ["status"])

    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
    )
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.Uuid()),
        sa.column("owner_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_personal", sa.Boolean()),
        sa.column("settings", sa.JSON()),
    )
    members = sa.table(
        "workspace_members",
        sa.column("workspace_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("role", sa.String()),
    )
    chats = sa.table(
        "chats",
        sa.column("user_id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
    )
    files = sa.table(
        "files",
        sa.column("user_id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
    )

    for user_id, _name in bind.execute(sa.select(users.c.id, users.c.name)):
        workspace_id = uuid.uuid4()
        bind.execute(
            workspaces.insert().values(
                id=workspace_id,
                owner_id=user_id,
                name="Personal",
                description="Your chats, files, and generated artifacts.",
                is_personal=True,
                settings={},
            )
        )
        bind.execute(
            members.insert().values(
                workspace_id=workspace_id,
                user_id=user_id,
                role="owner",
            )
        )
        bind.execute(
            chats.update().where(chats.c.user_id == user_id).values(workspace_id=workspace_id)
        )
        bind.execute(
            files.update().where(files.c.user_id == user_id).values(workspace_id=workspace_id)
        )


def downgrade() -> None:
    op.drop_index("ix_chat_runs_status", table_name="chat_runs")
    op.drop_index("ix_chat_runs_assistant_message_id", table_name="chat_runs")
    op.drop_index("ix_chat_runs_user_id", table_name="chat_runs")
    op.drop_index("ix_chat_runs_chat_id", table_name="chat_runs")
    op.drop_table("chat_runs")
    with op.batch_alter_table("files") as batch:
        batch.drop_index("ix_files_workspace_id")
        batch.drop_constraint("fk_files_workspace_id_workspaces", type_="foreignkey")
        batch.drop_column("workspace_id")
    with op.batch_alter_table("chats") as batch:
        batch.drop_index("ix_chats_workspace_id")
        batch.drop_constraint("fk_chats_workspace_id_workspaces", type_="foreignkey")
        batch.drop_column("workspace_id")
    op.drop_table("workspace_members")
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_table("workspaces")
