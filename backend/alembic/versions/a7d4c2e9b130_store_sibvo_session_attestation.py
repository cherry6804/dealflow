"""Store SIBVO session references for active access revalidation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d4c2e9b130"
down_revision: str | Sequence[str] | None = "f5b7c9d1e3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("sibvo_subject", sa.Uuid(), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("sibvo_organization_id", sa.Uuid(), nullable=True),
    )
    op.add_column("auth_sessions", sa.Column("sibvo_session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("sso_last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_sessions_sibvo_subject", "auth_sessions", ["sibvo_subject"])
    op.create_index("ix_auth_sessions_sibvo_session_id", "auth_sessions", ["sibvo_session_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_sibvo_session_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_sibvo_subject", table_name="auth_sessions")
    op.drop_column("auth_sessions", "sso_last_verified_at")
    op.drop_column("auth_sessions", "sibvo_session_id")
    op.drop_column("auth_sessions", "sibvo_organization_id")
    op.drop_column("auth_sessions", "sibvo_subject")
