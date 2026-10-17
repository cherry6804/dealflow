
"""Create tenant-scoped deal commissions."""

from alembic import op
import sqlalchemy as sa


revision = "c3f8a2d71940"
down_revision = "b2e6a71c904d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deal_commissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("commission_type", sa.String(length=20), nullable=False),
        sa.Column("fixed_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("rate_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="INR",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PROPOSED",
            nullable=False,
        ),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(length=200), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
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
            "commission_type IN ('FIXED', 'PERCENTAGE')",
            name="ck_deal_commissions_type",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'AGREED', 'PAID', 'CANCELLED')",
            name="ck_deal_commissions_status",
        ),
        sa.CheckConstraint(
            """
            (
                commission_type = 'FIXED'
                AND fixed_amount IS NOT NULL
                AND fixed_amount > 0
                AND rate_percent IS NULL
            )
            OR
            (
                commission_type = 'PERCENTAGE'
                AND rate_percent IS NOT NULL
                AND rate_percent > 0
                AND rate_percent <= 100
                AND fixed_amount IS NULL
            )
            """,
            name="ck_deal_commissions_amount_or_rate",
        ),
        sa.CheckConstraint(
            "status != 'PAID' OR paid_at IS NOT NULL",
            name="ck_deal_commissions_paid_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_deal_commissions_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_deal_commissions_deal_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_deal_commissions_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_deal_commissions_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_deal_commissions_organization_id",
        "deal_commissions",
        ["organization_id"],
    )
    op.create_index(
        "ix_deal_commissions_status",
        "deal_commissions",
        ["status"],
    )
    op.create_index(
        "ix_deal_commissions_org_deal",
        "deal_commissions",
        ["organization_id", "deal_id"],
    )
    op.create_index(
        "ix_deal_commissions_org_status",
        "deal_commissions",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deal_commissions_org_status",
        table_name="deal_commissions",
    )
    op.drop_index(
        "ix_deal_commissions_org_deal",
        table_name="deal_commissions",
    )
    op.drop_index(
        "ix_deal_commissions_status",
        table_name="deal_commissions",
    )
    op.drop_index(
        "ix_deal_commissions_organization_id",
        table_name="deal_commissions",
    )
    op.drop_table("deal_commissions")
