"""Allow Telegram /start to create a pending WebUI link.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("telegram_link_tokens") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("telegram_user_id", sa.String(length=100), nullable=True))
        batch.create_index("ix_telegram_link_tokens_telegram_user_id", ["telegram_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("telegram_link_tokens") as batch:
        batch.drop_index("ix_telegram_link_tokens_telegram_user_id")
        batch.drop_column("telegram_user_id")
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)
