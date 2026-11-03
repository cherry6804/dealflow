"""Attribute AI usage to a capability for breakdowns (DFR1-017).

Additive. Adds a nullable ``capability_key`` to ``ai_usage_events``. Existing entries stay null and are shown as
unattributed. Reservation expiry, release reasons and configurable alert thresholds are already provided by the
hardened usage ledger and its migrations (``e6b1d7a4c9f2`` and ``f2a8c4e6b0d3``), so this migration adds nothing else.
Downgrade drops only this column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k2b7d4e9a1c3"
down_revision: str | Sequence[str] | None = "j1a6e3c9b4d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_usage_events", sa.Column("capability_key", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_usage_events", "capability_key")
