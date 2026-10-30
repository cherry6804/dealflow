"""Enforce one reconciliation record per webhook event.

Revision ID: 7a2c9e4d61b8
Revises: 05f11754c0a9
"""

from alembic import op

revision = "7a2c9e4d61b8"
down_revision = "05f11754c0a9"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_billing_reconciliation_records_webhook_event"


def upgrade() -> None:
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "billing_reconciliation_records",
        ["webhook_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "billing_reconciliation_records",
        type_="unique",
    )