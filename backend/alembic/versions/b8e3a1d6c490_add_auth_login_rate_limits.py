"""Add shared login rate-limit counters."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8e3a1d6c490"
down_revision: str | Sequence[str] | None = "a7d4c2e9b130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_login_rate_limits",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_auth_login_rate_limits_window",
        "auth_login_rate_limits",
        ["window_started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_login_rate_limits_window",
        table_name="auth_login_rate_limits",
    )
    op.drop_table("auth_login_rate_limits")
