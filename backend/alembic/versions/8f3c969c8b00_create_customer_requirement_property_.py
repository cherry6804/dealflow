"""create customer requirement property preferences

Revision ID: 8f3c969c8b00
Revises: 9a7c2e41d5b8
Create Date: 2026-10-05 17:56:37.658507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f3c969c8b00"
down_revision: Union[str, Sequence[str], None] = "9a7c2e41d5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "customer_requirement_property_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("property_type", sa.String(length=50), nullable=False),
        sa.Column("bhk_min", sa.Integer(), nullable=True),
        sa.Column("bhk_max", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        op.f(
            "ix_customer_requirement_property_preferences_customer_requirement_id"
        ),
        "customer_requirement_property_preferences",
        ["customer_requirement_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_customer_requirement_property_preferences_is_active"),
        "customer_requirement_property_preferences",
        ["is_active"],
        unique=False,
    )

    op.create_index(
        op.f("ix_customer_requirement_property_preferences_organization_id"),
        "customer_requirement_property_preferences",
        ["organization_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_customer_requirement_property_preferences_property_type"),
        "customer_requirement_property_preferences",
        ["property_type"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_customer_requirement_property_preferences_property_type"),
        table_name="customer_requirement_property_preferences",
    )

    op.drop_index(
        op.f("ix_customer_requirement_property_preferences_organization_id"),
        table_name="customer_requirement_property_preferences",
    )

    op.drop_index(
        op.f("ix_customer_requirement_property_preferences_is_active"),
        table_name="customer_requirement_property_preferences",
    )

    op.drop_index(
        op.f(
            "ix_customer_requirement_property_preferences_customer_requirement_id"
        ),
        table_name="customer_requirement_property_preferences",
    )

    op.drop_table("customer_requirement_property_preferences")