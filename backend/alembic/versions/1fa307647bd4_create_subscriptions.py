
"""create subscriptions

Revision ID: 1fa307647bd4
Revises: 2199716b7a66
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1fa307647bd4"
down_revision: Union[str, Sequence[str], None] = "2199716b7a66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tenant-scoped subscriptions."""
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("plan_code", sa.String(length=80), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "billing_interval",
            sa.String(length=10),
            server_default="MONTHLY",
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column(
            "provider_customer_id",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "provider_subscription_id",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "current_period_start",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "current_period_end",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "trial_ends_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('TRIALING', 'PENDING', 'ACTIVE', 'PAST_DUE', "
            "'PAUSED', 'CANCELLED', 'EXPIRED')",
            name="ck_subscriptions_status",
        ),
        sa.CheckConstraint(
            "billing_interval IN ('MONTHLY', 'YEARLY')",
            name="ck_subscriptions_billing_interval",
        ),
        sa.CheckConstraint(
            "length(plan_code) > 0",
            name="ck_subscriptions_plan_code_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_subscriptions_organization_id",
        "subscriptions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions_org_status",
        "subscriptions",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions_org_period_end",
        "subscriptions",
        ["organization_id", "current_period_end"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions_provider_subscription",
        "subscriptions",
        ["provider", "provider_subscription_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop subscriptions."""
    op.drop_index(
        "ix_subscriptions_provider_subscription",
        table_name="subscriptions",
    )
    op.drop_index(
        "ix_subscriptions_org_period_end",
        table_name="subscriptions",
    )
    op.drop_index(
        "ix_subscriptions_org_status",
        table_name="subscriptions",
    )
    op.drop_index(
        "ix_subscriptions_organization_id",
        table_name="subscriptions",
    )
    op.drop_table("subscriptions")
