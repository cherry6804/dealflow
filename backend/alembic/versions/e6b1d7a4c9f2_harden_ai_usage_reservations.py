"""Harden AI usage reservations: expiry, request fingerprints and status constraints (WS6 WP1).

Adds three nullable columns to ``ai_usage_events``:

- ``request_fingerprint`` detects a reused idempotency key sent with a different payload.
- ``reservation_expires_at`` lets the reaper release a reservation that was never settled.
- ``released_reason`` records why a reservation left the RESERVED state (released or expired).

Historical rows are preserved. Existing RESERVED rows receive an expiry of ``created_at`` plus
the reservation TTL (15 minutes, the same value as ``RESERVATION_TTL`` in the application), so an
abandoned pre-WP1 reservation is recovered by the reaper instead of holding budget indefinitely.
Their fingerprint stays null, which the application treats as "cannot be compared".

Two check constraints guard the status values and require an expiry on every open reservation.
If an existing row already violates either rule, this migration fails and changes nothing.

Downgrade drops the constraints, index and columns. Reservations that are still open remain in
the RESERVED state and lose their expiry, so they must be settled or released manually after a
downgrade. Released and reversed history is kept.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6b1d7a4c9f2"
down_revision: str | Sequence[str] | None = "d4e9a2c6f8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors RESERVATION_TTL in app/governance/usage_ledger.py. Migrations must not import app code.
RESERVATION_TTL_INTERVAL = "15 minutes"


def upgrade() -> None:
    op.add_column("ai_usage_events", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "ai_usage_events",
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("ai_usage_events", sa.Column("released_reason", sa.String(length=40), nullable=True))

    op.execute(
        sa.text(
            "UPDATE ai_usage_events "
            "SET reservation_expires_at = created_at + CAST(:ttl AS interval) "
            "WHERE status = 'reserved' AND reservation_expires_at IS NULL"
        ).bindparams(ttl=RESERVATION_TTL_INTERVAL)
    )

    op.create_check_constraint(
        "ck_ai_usage_events_status",
        "ai_usage_events",
        "status IN ('reserved', 'recorded', 'released', 'reversed')",
    )
    op.create_check_constraint(
        "ck_ai_usage_events_reservation_expiry",
        "ai_usage_events",
        "status <> 'reserved' OR reservation_expires_at IS NOT NULL",
    )
    op.create_index(
        "ix_ai_usage_events_reserved_expiry",
        "ai_usage_events",
        ["reservation_expires_at"],
        postgresql_where=sa.text("status = 'reserved'"),
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_reserved_expiry", table_name="ai_usage_events")
    op.drop_constraint("ck_ai_usage_events_reservation_expiry", "ai_usage_events", type_="check")
    op.drop_constraint("ck_ai_usage_events_status", "ai_usage_events", type_="check")
    op.drop_column("ai_usage_events", "released_reason")
    op.drop_column("ai_usage_events", "reservation_expires_at")
    op.drop_column("ai_usage_events", "request_fingerprint")
