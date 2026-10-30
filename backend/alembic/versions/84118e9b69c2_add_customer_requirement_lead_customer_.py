"""add customer requirement lead customer profile associations

Revision ID: 84118e9b69c2
Revises: c2b4db856311
Create Date: 2026-10-05 22:38:53.591953

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "84118e9b69c2"
down_revision: Union[str, Sequence[str], None] = "c2b4db856311"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "customer_requirements",
        sa.Column("lead_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "customer_requirements",
        sa.Column("customer_profile_id", sa.Uuid(), nullable=True),
    )

    op.create_index(
        op.f("ix_customer_requirements_lead_id"),
        "customer_requirements",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_requirements_customer_profile_id"),
        "customer_requirements",
        ["customer_profile_id"],
        unique=False,
    )

    # These composite unique constraints are required so PostgreSQL
    # can enforce the tenant-safe composite foreign keys below.
    op.create_unique_constraint(
        "uq_leads_id_organization_id",
        "leads",
        ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_customer_profiles_id_organization_id",
        "customer_profiles",
        ["id", "organization_id"],
    )

    op.create_foreign_key(
        "fk_customer_requirements_lead_tenant",
        "customer_requirements",
        "leads",
        ["lead_id", "organization_id"],
        ["id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_customer_requirements_customer_profile_tenant",
        "customer_requirements",
        "customer_profiles",
        ["customer_profile_id", "organization_id"],
        ["id", "organization_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_customer_requirements_customer_profile_tenant",
        "customer_requirements",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_customer_requirements_lead_tenant",
        "customer_requirements",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_customer_profiles_id_organization_id",
        "customer_profiles",
        type_="unique",
    )
    op.drop_constraint(
        "uq_leads_id_organization_id",
        "leads",
        type_="unique",
    )

    op.drop_index(
        op.f("ix_customer_requirements_customer_profile_id"),
        table_name="customer_requirements",
    )
    op.drop_index(
        op.f("ix_customer_requirements_lead_id"),
        table_name="customer_requirements",
    )

    op.drop_column(
        "customer_requirements",
        "customer_profile_id",
    )
    op.drop_column(
        "customer_requirements",
        "lead_id",
    )