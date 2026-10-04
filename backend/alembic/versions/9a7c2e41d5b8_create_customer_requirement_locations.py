"""Create customer requirement locations.

Revision ID: 9a7c2e41d5b8
Revises: 781f4ebc1fa2
Create Date: 2026-10-04 14:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a7c2e41d5b8"
down_revision: Union[str, None] = "781f4ebc1fa2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the customer requirement locations table."""

    op.create_unique_constraint(
        "uq_customer_requirements_id_organization_id",
        "customer_requirements",
        ["id", "organization_id"],
    )

    op.create_table(
        "customer_requirement_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("city", sa.String(length=150), nullable=False),
        sa.Column("locality", sa.String(length=200), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            [
                "customer_requirements.id",
                "customer_requirements.organization_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_customer_requirement_locations_organization_id",
        "customer_requirement_locations",
        ["organization_id"],
        unique=False,
    )

    op.create_index(
        "ix_customer_requirement_locations_customer_requirement_id",
        "customer_requirement_locations",
        ["customer_requirement_id"],
        unique=False,
    )

    op.create_index(
        "ix_customer_requirement_locations_is_active",
        "customer_requirement_locations",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the customer requirement locations table."""

    op.drop_index(
        "ix_customer_requirement_locations_is_active",
        table_name="customer_requirement_locations",
    )

    op.drop_index(
        "ix_customer_requirement_locations_customer_requirement_id",
        table_name="customer_requirement_locations",
    )

    op.drop_index(
        "ix_customer_requirement_locations_organization_id",
        table_name="customer_requirement_locations",
    )

    op.drop_table("customer_requirement_locations")

    op.drop_constraint(
        "uq_customer_requirements_id_organization_id",
        "customer_requirements",
        type_="unique",
    )