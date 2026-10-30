
"""Create tenant-scoped deals.

Revision ID: 7f4d9c2e1a63
Revises: 62d2c29d8337
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f4d9c2e1a63"
down_revision: str | Sequence[str] | None = "62d2c29d8337"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_profile_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "stage",
            sa.String(length=30),
            server_default="NEW",
            nullable=False,
        ),
        sa.Column("expected_value", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="INR",
            nullable=False,
        ),
        sa.Column("notes", sa.String(length=2000), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_deals_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            ["customer_profiles.id", "customer_profiles.organization_id"],
            name="fk_deals_customer_profile_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["property_id", "organization_id"],
            ["properties.id", "properties.organization_id"],
            name="fk_deals_property_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_deals_lead_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_deals_owner_membership_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deals"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_deals_id_organization_id",
        ),
    )

    op.create_index(
        "ix_deals_organization_id",
        "deals",
        ["organization_id"],
    )
    op.create_index(
        "ix_deals_customer_profile_id",
        "deals",
        ["customer_profile_id"],
    )
    op.create_index("ix_deals_property_id", "deals", ["property_id"])
    op.create_index("ix_deals_lead_id", "deals", ["lead_id"])
    op.create_index("ix_deals_owner_user_id", "deals", ["owner_user_id"])
    op.create_index("ix_deals_stage", "deals", ["stage"])


def downgrade() -> None:
    op.drop_index("ix_deals_stage", table_name="deals")
    op.drop_index("ix_deals_owner_user_id", table_name="deals")
    op.drop_index("ix_deals_lead_id", table_name="deals")
    op.drop_index("ix_deals_property_id", table_name="deals")
    op.drop_index("ix_deals_customer_profile_id", table_name="deals")
    op.drop_index("ix_deals_organization_id", table_name="deals")
    op.drop_table("deals")
