"""add site visits

Revision ID: 54c638689803
Revises: 46683ea97897
Create Date: 2026-10-16 09:26:29.224799
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "54c638689803"
down_revision: Union[str, Sequence[str], None] = "46683ea97897"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tenant-safe site visits."""
    # Create the referenced composite key before adding its foreign key.
    op.create_unique_constraint(
        "uq_properties_id_organization_id",
        "properties",
        ["id", "organization_id"],
    )

    op.create_table(
        "site_visits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("customer_profile_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="SCHEDULED",
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('INTERESTED', 'NOT_INTERESTED', 'NEGOTIATION', "
            "'FOLLOW_UP_REQUIRED', 'OTHER')",
            name="ck_site_visits_outcome",
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name="ck_site_visits_status",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > scheduled_at",
            name="ck_site_visits_time_range",
        ),
        sa.CheckConstraint(
            "lead_id IS NOT NULL OR customer_profile_id IS NOT NULL",
            name="ck_site_visits_customer_reference",
        ),
        sa.ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            ["customer_profiles.id", "customer_profiles.organization_id"],
            name="fk_site_visits_customer_profile_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_site_visits_lead_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_site_visits_owner_membership_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["property_id", "organization_id"],
            ["properties.id", "properties.organization_id"],
            name="fk_site_visits_property_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_site_visits_id_organization",
        ),
    )

    op.create_index(
        "ix_site_visits_org_owner_status_scheduled",
        "site_visits",
        ["organization_id", "owner_user_id", "status", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_site_visits_org_property_scheduled",
        "site_visits",
        ["organization_id", "property_id", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_site_visits_org_scheduled_at",
        "site_visits",
        ["organization_id", "scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove site visits and their supporting property constraint."""
    op.drop_table("site_visits")
    op.drop_constraint(
        "uq_properties_id_organization_id",
        "properties",
        type_="unique",
    )
