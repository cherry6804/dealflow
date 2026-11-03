"""Add reservation expiry, capability attribution and configurable usage alert thresholds (DFR1-017).

Additive. Existing usage entries get null expiry, release reason and capability. Existing budgets get
the default thresholds 70 (warning) and 85 (critical), which match the previous fixed behaviour. Downgrade
drops only these columns.
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
    op.add_column("ai_usage_events", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_usage_events", sa.Column("release_reason", sa.String(length=40), nullable=True))
    op.create_index(
        "ix_ai_usage_events_reserved_expiry",
        "ai_usage_events",
        ["status", "expires_at"],
    )
    op.add_column(
        "organization_usage_budgets",
        sa.Column("warning_percent", sa.Integer(), nullable=False, server_default="70"),
    )
    op.add_column(
        "organization_usage_budgets",
        sa.Column("critical_percent", sa.Integer(), nullable=False, server_default="85"),
    )
    op.create_check_constraint(
        "ck_organization_usage_budgets_thresholds",
        "organization_usage_budgets",
        "warning_percent >= 1 AND critical_percent > warning_percent AND critical_percent < 100",
    )


def downgrade() -> None:
    op.drop_constraint("ck_organization_usage_budgets_thresholds", "organization_usage_budgets", type_="check")
    op.drop_column("organization_usage_budgets", "critical_percent")
    op.drop_column("organization_usage_budgets", "warning_percent")
    op.drop_index("ix_ai_usage_events_reserved_expiry", table_name="ai_usage_events")
    op.drop_column("ai_usage_events", "release_reason")
    op.drop_column("ai_usage_events", "expires_at")
    op.drop_column("ai_usage_events", "capability_key")
