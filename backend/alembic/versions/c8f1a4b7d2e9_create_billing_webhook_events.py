
"""Create persistent billing webhook events.

Revision ID: c8f1a4b7d2e9
Revises: a530aec6d3d1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8f1a4b7d2e9"
down_revision: Union[str, Sequence[str], None] = "a530aec6d3d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the durable webhook event table."""

    op.create_table(
        "billing_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column(
            "provider_event_id",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="RECEIVED",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED')",
            name="ck_billing_webhook_events_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_billing_webhook_events_attempt_count",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_billing_webhook_events_provider_event",
        ),
    )

    op.create_index(
        "ix_billing_webhook_events_status_received",
        "billing_webhook_events",
        ["status", "received_at"],
    )


def downgrade() -> None:
    """Remove the webhook event table."""

    op.drop_index(
        "ix_billing_webhook_events_status_received",
        table_name="billing_webhook_events",
    )
    op.drop_table("billing_webhook_events")
