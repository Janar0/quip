"""Persist Telegram updates until the bridge has handled them.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("update_id"),
    )
    op.create_index("ix_telegram_updates_status", "telegram_updates", ["status"])
    op.create_index("ix_telegram_updates_available_at", "telegram_updates", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_updates_available_at", table_name="telegram_updates")
    op.drop_index("ix_telegram_updates_status", table_name="telegram_updates")
    op.drop_table("telegram_updates")
