"""Add background processing columns to privacy data requests (DFR1-050).

Adds the attempt counter, processing time and per-category execution record used by the
privacy outbox handler. Existing request rows keep their status and gain empty execution
records. Downgrade removes only these columns; request rows are not deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j1a6e3c9b4d2"
down_revision: str | Sequence[str] | None = "i7f2c9d4e1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "privacy_data_requests",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "privacy_data_requests",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "privacy_data_requests",
        sa.Column("execution", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("privacy_data_requests", "execution")
    op.drop_column("privacy_data_requests", "processed_at")
    op.drop_column("privacy_data_requests", "attempt_count")
