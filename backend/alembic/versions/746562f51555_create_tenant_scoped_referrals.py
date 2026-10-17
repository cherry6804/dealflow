
"""Create tenant-scoped referrals."""

from alembic import op
import sqlalchemy as sa


revision = "746562f51555"
down_revision = "d4e7b9a21650"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referrals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_profile_id", sa.Uuid(), nullable=True),
        sa.Column("referrer_contact_id", sa.Uuid(), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("referral_name", sa.String(length=200), nullable=False),
        sa.Column("referral_phone", sa.String(length=50), nullable=True),
        sa.Column("referral_email", sa.String(length=320), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="NEW",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
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
            "status IN ('NEW', 'CONTACTED', 'CONVERTED', 'NOT_CONVERTED')",
            name="ck_referrals_status",
        ),
        sa.CheckConstraint(
            """
            customer_profile_id IS NOT NULL
            OR referrer_contact_id IS NOT NULL
            OR deal_id IS NOT NULL
            """,
            name="ck_referrals_has_association",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_referrals_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            ["customer_profiles.id", "customer_profiles.organization_id"],
            name="fk_referrals_customer_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["referrer_contact_id", "organization_id"],
            ["contacts.id", "contacts.organization_id"],
            name="fk_referrals_referrer_contact_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_referrals_deal_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_referrals_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_referrals_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_referrals_organization_id",
        "referrals",
        ["organization_id"],
    )
    op.create_index(
        "ix_referrals_org_status",
        "referrals",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_referrals_org_customer",
        "referrals",
        ["organization_id", "customer_profile_id"],
    )
    op.create_index(
        "ix_referrals_org_referrer",
        "referrals",
        ["organization_id", "referrer_contact_id"],
    )
    op.create_index(
        "ix_referrals_org_deal",
        "referrals",
        ["organization_id", "deal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_referrals_org_deal", table_name="referrals")
    op.drop_index("ix_referrals_org_referrer", table_name="referrals")
    op.drop_index("ix_referrals_org_customer", table_name="referrals")
    op.drop_index("ix_referrals_org_status", table_name="referrals")
    op.drop_index("ix_referrals_organization_id", table_name="referrals")
    op.drop_table("referrals")
