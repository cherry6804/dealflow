
"""Create tenant-scoped deal payment milestones."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a8f3c91d6e42"
down_revision: str | Sequence[str] | None = "8d71b3c2e940"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="INR",
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(length=200), nullable=True),
        sa.Column("paid_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_payment_milestones_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PAID', 'CANCELLED')",
            name="ck_payment_milestones_status",
        ),
        sa.CheckConstraint(
            "status != 'PAID' OR paid_at IS NOT NULL",
            name="ck_payment_milestones_paid_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_payment_milestones_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_payment_milestones_deal_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paid_by_user_id"],
            ["users.id"],
            name="fk_payment_milestones_paid_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_payment_milestones_created_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_milestones"),
    )

    op.create_index(
        "ix_payment_milestones_organization_id",
        "payment_milestones",
        ["organization_id"],
    )
    op.create_index(
        "ix_payment_milestones_org_deal_due",
        "payment_milestones",
        ["organization_id", "deal_id", "due_at"],
    )
    op.create_index(
        "ix_payment_milestones_org_status_due",
        "payment_milestones",
        ["organization_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_milestones_org_status_due",
        table_name="payment_milestones",
    )
    op.drop_index(
        "ix_payment_milestones_org_deal_due",
        table_name="payment_milestones",
    )
    op.drop_index(
        "ix_payment_milestones_organization_id",
        table_name="payment_milestones",
    )
    op.drop_table("payment_milestones")
