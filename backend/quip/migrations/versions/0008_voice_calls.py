"""Persist voice session and idempotent provider tool-call metadata.

Revision ID: 0008
Revises: 0007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("context_version", sa.String(length=80), nullable=True),
        sa.Column("camera_enabled", sa.Boolean(), nullable=False),
        sa.Column("client_usage", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_calls_user_id", "voice_calls", ["user_id"])
    op.create_index("ix_voice_calls_chat_id", "voice_calls", ["chat_id"])
    op.create_index("ix_voice_calls_status", "voice_calls", ["status"])
    op.create_table(
        "voice_tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voice_call_id", sa.Uuid(), nullable=False),
        sa.Column("provider_call_id", sa.String(length=160), nullable=False),
        sa.Column("function_name", sa.String(length=80), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("result_message_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["result_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voice_call_id"], ["voice_calls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_call_id", "provider_call_id", name="uq_voice_tool_call_provider_id"),
    )
    op.create_index("ix_voice_tool_calls_voice_call_id", "voice_tool_calls", ["voice_call_id"])
    op.create_index("ix_voice_tool_calls_status", "voice_tool_calls", ["status"])


def downgrade() -> None:
    op.drop_index("ix_voice_tool_calls_status", table_name="voice_tool_calls")
    op.drop_index("ix_voice_tool_calls_voice_call_id", table_name="voice_tool_calls")
    op.drop_table("voice_tool_calls")
    op.drop_index("ix_voice_calls_status", table_name="voice_calls")
    op.drop_index("ix_voice_calls_chat_id", table_name="voice_calls")
    op.drop_index("ix_voice_calls_user_id", table_name="voice_calls")
    op.drop_table("voice_calls")
