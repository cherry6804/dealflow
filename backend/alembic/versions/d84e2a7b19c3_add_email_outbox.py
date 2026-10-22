
"""Add encrypted email delivery outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d84e2a7b19c3"
down_revision: str | Sequence[str] | None = "c2377a42e482"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistent email outbox storage."""
    op.create_table(
        "email_outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_email_outbox_ready",
        "email_outbox_messages",
        ["status", "available_at", "locked_until"],
        unique=False,
    )

    op.create_index(
        "ix_email_outbox_created",
        "email_outbox_messages",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove email outbox storage."""
    op.drop_index(
        "ix_email_outbox_created",
        table_name="email_outbox_messages",
    )
    op.drop_index(
        "ix_email_outbox_ready",
        table_name="email_outbox_messages",
    )
    op.drop_table("email_outbox_messages")