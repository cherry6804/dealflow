
"""Create tenant-scoped in-app notifications."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f6a91c2d830"
down_revision: str | Sequence[str] | None = "8a42c1d7e690"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistent notification records."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=200), nullable=True),
        sa.Column("event_key", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_notifications_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_notifications_recipient_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "recipient_user_id",
            "event_key",
            name="uq_notifications_recipient_event_key",
        ),
    )

    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["organization_id", "recipient_user_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_notifications_recipient_read_created",
        "notifications",
        ["organization_id", "recipient_user_id", "read_at", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_notifications_org_event_created",
        "notifications",
        ["organization_id", "event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove notification storage."""
    op.drop_index(
        "ix_notifications_org_event_created",
        table_name="notifications",
    )
    op.drop_index(
        "ix_notifications_recipient_read_created",
        table_name="notifications",
    )
    op.drop_index(
        "ix_notifications_recipient_created",
        table_name="notifications",
    )
    op.drop_table("notifications")
