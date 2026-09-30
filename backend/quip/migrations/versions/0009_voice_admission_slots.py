"""Make voice session and tool admission race-safe.

Revision ID: 0009
Revises: 0008
"""
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("voice_tool_calls", sa.Column("admission_slot", sa.Integer(), nullable=True))
    op.add_column("voice_tool_calls", sa.Column("search_slot", sa.Integer(), nullable=True))
    op.add_column("voice_tool_calls", sa.Column("pending_slot", sa.Integer(), nullable=True))
    op.add_column("voice_tool_calls", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))

    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT id, voice_call_id, function_name, status FROM voice_tool_calls ORDER BY created_at, id"
    )).mappings().all()
    by_call: dict[str, list] = defaultdict(list)
    for row in rows:
        by_call[str(row["voice_call_id"])].append(row)
    for call_rows in by_call.values():
        search_slot = 0
        pending_assigned = False
        for admission_slot, row in enumerate(call_rows):
            connection.execute(sa.text(
                "UPDATE voice_tool_calls SET admission_slot=:admission_slot, search_slot=:search_slot, "
                "pending_slot=:pending_slot WHERE id=:id"
            ), {
                "id": row["id"],
                "admission_slot": admission_slot if admission_slot < 10 else None,
                "search_slot": (search_slot if row["function_name"] == "web_search" and search_slot < 5 else None),
                "pending_slot": 1 if row["status"] == "pending" and not pending_assigned else None,
            })
            if row["function_name"] == "web_search" and search_slot < 5:
                search_slot += 1
            pending_assigned |= row["status"] == "pending"

    op.create_index(
        "uq_voice_tool_call_admission_slot", "voice_tool_calls", ["voice_call_id", "admission_slot"], unique=True
    )
    op.create_index(
        "uq_voice_tool_call_search_slot", "voice_tool_calls", ["voice_call_id", "search_slot"], unique=True
    )
    op.create_index(
        "uq_voice_tool_call_pending_slot", "voice_tool_calls", ["voice_call_id", "pending_slot"], unique=True
    )

    # An app restart closes provider peer connections; settle any old duplicate
    # active rows before enforcing one session per account.
    connection.execute(sa.text(
        "UPDATE voice_calls SET status='failed', error_code='session_recovered_during_upgrade', "
        "ended_at=CURRENT_TIMESTAMP WHERE status IN ('connecting', 'active') AND id NOT IN ("
        "SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC, id DESC) AS rn "
        "FROM voice_calls WHERE status IN ('connecting', 'active')) AS ranked WHERE rn=1)"
    ))
    op.create_index(
        "uq_voice_calls_one_active_per_user", "voice_calls", ["user_id"], unique=True,
        sqlite_where=sa.text("status IN ('connecting', 'active')"),
        postgresql_where=sa.text("status IN ('connecting', 'active')"),
    )


def downgrade() -> None:
    op.drop_index("uq_voice_calls_one_active_per_user", table_name="voice_calls")
    op.drop_index("uq_voice_tool_call_pending_slot", table_name="voice_tool_calls")
    op.drop_index("uq_voice_tool_call_search_slot", table_name="voice_tool_calls")
    op.drop_index("uq_voice_tool_call_admission_slot", table_name="voice_tool_calls")
    op.drop_column("voice_tool_calls", "pending_slot")
    op.drop_column("voice_tool_calls", "search_slot")
    op.drop_column("voice_tool_calls", "admission_slot")
    op.drop_column("voice_tool_calls", "cancel_requested")
