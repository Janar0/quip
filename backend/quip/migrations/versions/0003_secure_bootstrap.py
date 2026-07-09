"""Make first-administrator bootstrap an atomic one-time claim.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bootstrap_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("claimed_by", sa.Uuid()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("role", sa.String()),
    )
    state = sa.table(
        "bootstrap_state",
        sa.column("id", sa.Integer()),
        sa.column("completed", sa.Boolean()),
        sa.column("claimed_by", sa.Uuid()),
        sa.column("completed_at", sa.DateTime(timezone=True)),
    )
    existing = bind.execute(
        sa.select(users.c.id).order_by((users.c.role == "admin").desc()).limit(1)
    ).scalar_one_or_none()
    bind.execute(
        state.insert().values(
            id=1,
            completed=existing is not None,
            claimed_by=existing,
            completed_at=sa.func.now() if existing is not None else None,
        )
    )


def downgrade() -> None:
    op.drop_table("bootstrap_state")
