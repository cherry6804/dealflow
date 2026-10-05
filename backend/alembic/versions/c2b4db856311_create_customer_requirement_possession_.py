"""create customer requirement possession parking preferences

Revision ID: c2b4db856311
Revises: 8f3c969c8b00
Create Date: 2026-10-05 21:12:37.180175

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2b4db856311"
down_revision: Union[str, Sequence[str], None] = "8f3c969c8b00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create customer requirement possession and parking preferences."""

    op.create_table(
        "customer_requirement_possession_parking_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("customer_requirement_id", sa.UUID(), nullable=False),
        sa.Column("possession_preference", sa.String(length=50), nullable=False),
        sa.Column("parking_preference", sa.String(length=50), nullable=False),
        sa.Column("parking_spaces_min", sa.Integer(), nullable=True),
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
            name="fk_req_possession_parking_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_requirement_id",
            "organization_id",
            name="uq_req_possession_parking_req",
        ),
    )

    op.create_index(
        "ix_req_possession_parking_org",
        "customer_requirement_possession_parking_preferences",
        ["organization_id"],
        unique=False,
    )

    op.create_index(
        "ix_req_possession_parking_req",
        "customer_requirement_possession_parking_preferences",
        ["customer_requirement_id"],
        unique=False,
    )

    op.create_index(
        "ix_req_possession_parking_active",
        "customer_requirement_possession_parking_preferences",
        ["is_active"],
        unique=False,
    )

    op.create_index(
        "ix_req_possession_parking_possession",
        "customer_requirement_possession_parking_preferences",
        ["possession_preference"],
        unique=False,
    )

    op.create_index(
        "ix_req_possession_parking_parking",
        "customer_requirement_possession_parking_preferences",
        ["parking_preference"],
        unique=False,
    )


def downgrade() -> None:
    """Drop customer requirement possession and parking preferences."""

    op.drop_index(
        "ix_req_possession_parking_parking",
        table_name="customer_requirement_possession_parking_preferences",
    )

    op.drop_index(
        "ix_req_possession_parking_possession",
        table_name="customer_requirement_possession_parking_preferences",
    )

    op.drop_index(
        "ix_req_possession_parking_active",
        table_name="customer_requirement_possession_parking_preferences",
    )

    op.drop_index(
        "ix_req_possession_parking_req",
        table_name="customer_requirement_possession_parking_preferences",
    )

    op.drop_index(
        "ix_req_possession_parking_org",
        table_name="customer_requirement_possession_parking_preferences",
    )

    op.drop_table(
        "customer_requirement_possession_parking_preferences",
    )