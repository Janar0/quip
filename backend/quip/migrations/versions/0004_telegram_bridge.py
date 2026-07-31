"""Add Telegram identity and external chat bindings.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("telegram_user_id", sa.String(length=100), nullable=True))
        batch.create_index("ix_users_telegram_user_id", ["telegram_user_id"], unique=True)

    with op.batch_alter_table("chats") as batch:
        batch.add_column(sa.Column("source", sa.String(length=20), nullable=False, server_default="web"))
        batch.add_column(sa.Column("external_chat_id", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("external_thread_id", sa.String(length=100), nullable=True))
        batch.create_index("ix_chats_source", ["source"], unique=False)
        batch.create_index("ix_chats_external_chat_id", ["external_chat_id"], unique=False)
        batch.create_index("ix_chats_external_thread_id", ["external_thread_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("chats") as batch:
        batch.drop_index("ix_chats_external_thread_id")
        batch.drop_index("ix_chats_external_chat_id")
        batch.drop_index("ix_chats_source")
        batch.drop_column("external_thread_id")
        batch.drop_column("external_chat_id")
        batch.drop_column("source")

    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_telegram_user_id")
        batch.drop_column("telegram_user_id")
