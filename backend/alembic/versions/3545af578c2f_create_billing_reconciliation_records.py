"""Create billing reconciliation records.

Revision ID: 3545af578c2f
Revises: c8f1a4b7d2e9
"""

from alembic import op
import sqlalchemy as sa

revision = "3545af578c2f"
down_revision = "c8f1a4b7d2e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_reconciliation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("webhook_event_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "reconciled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('MATCHED', 'MISMATCHED', 'FAILED')",
            name="ck_billing_reconciliation_records_status",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"],
            ["billing_webhook_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_reconciliation_records_event_created",
        "billing_reconciliation_records",
        ["webhook_event_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_reconciliation_records_event_created",
        table_name="billing_reconciliation_records",
    )
    op.drop_table("billing_reconciliation_records")