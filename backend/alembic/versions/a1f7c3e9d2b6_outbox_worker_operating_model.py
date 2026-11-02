"""Outbox worker operating model: lease fencing, dead-letter reasons and replay audit (WS3).

Additive only. Existing rows keep NULL in the new nullable columns. Rolling deploys must stop
workers that predate this revision before the new workers start, because those workers never
set ``claim_token`` and cannot pass the fence.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f7c3e9d2b6"
down_revision: str | Sequence[str] | None = "m3c8e0a2b4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("claim_token", sa.Uuid(), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("dead_letter_reason", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "outbox_replay_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("operator", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("previous_attempts", sa.Integer(), nullable=False),
        sa.Column("previous_dead_letter_reason", sa.String(length=64), nullable=True),
        sa.Column("previous_error", sa.String(length=500), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.id"],
            name="fk_outbox_replay_records_event_id_outbox_events",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_outbox_replay_records_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_replay_records"),
    )
    op.create_index(
        "ix_outbox_replay_records_event",
        "outbox_replay_records",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_replay_records_organization_requested",
        "outbox_replay_records",
        ["organization_id", "requested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_replay_records_organization_requested",
        table_name="outbox_replay_records",
    )
    op.drop_index("ix_outbox_replay_records_event", table_name="outbox_replay_records")
    op.drop_table("outbox_replay_records")
    op.drop_column("outbox_events", "dead_letter_reason")
    op.drop_column("outbox_events", "claim_token")
