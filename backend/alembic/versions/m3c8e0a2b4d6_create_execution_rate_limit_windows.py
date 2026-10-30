"""Create execution rate-limit windows (E13 hardening).

The table holds fixed-window request counters. Counters are operational state, not business
records: they can be recreated, and dropping them only resets current windows. The downgrade
therefore drops the table without a refusal guard.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m3c8e0a2b4d6"
down_revision: str | Sequence[str] | None = "l2b7d9f1a3c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_rate_limit_windows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("execution_type", sa.String(length=80), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "organization_id",
            "scope_type",
            "scope_id",
            "execution_type",
            name="uq_execution_rate_limit_windows_scope",
        ),
    )
    op.create_index(
        "ix_execution_rate_limit_windows_organization_id",
        "execution_rate_limit_windows",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_rate_limit_windows_organization_id",
        table_name="execution_rate_limit_windows",
    )
    op.drop_table("execution_rate_limit_windows")
