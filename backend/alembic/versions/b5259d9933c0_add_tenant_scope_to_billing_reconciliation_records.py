"""Add tenant scope to billing reconciliation records.

Revision ID: b5259d9933c0
Revises: 3545af578c2f
"""

from alembic import op
import sqlalchemy as sa

revision = "b5259d9933c0"
down_revision = "3545af578c2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_reconciliation_records",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_billing_reconciliation_records_organization_id",
        "billing_reconciliation_records",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_billing_reconciliation_records_organization_id",
        "billing_reconciliation_records",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_reconciliation_records_organization_id",
        table_name="billing_reconciliation_records",
    )
    op.drop_constraint(
        "fk_billing_reconciliation_records_organization_id",
        "billing_reconciliation_records",
        type_="foreignkey",
    )
    op.drop_column(
        "billing_reconciliation_records",
        "organization_id",
    )