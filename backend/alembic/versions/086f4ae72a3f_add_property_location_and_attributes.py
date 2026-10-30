"""add property location and attributes

Revision ID: 086f4ae72a3f
Revises: 5d9bf31e3dd3
Create Date: 2026-10-08 19:55:10.174197

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "086f4ae72a3f"
down_revision: Union[str, Sequence[str], None] = "5d9bf31e3dd3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "properties",
        sa.Column(
            "address_line_1",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "address_line_2",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "locality",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "city",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "state",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "postal_code",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "property_type",
            sa.String(length=30),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "bhk",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "built_up_area",
            sa.Numeric(
                precision=20,
                scale=2,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "carpet_area",
            sa.Numeric(
                precision=20,
                scale=2,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "floor_number",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "properties",
        sa.Column(
            "total_floors",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column(
        "properties",
        "total_floors",
    )
    op.drop_column(
        "properties",
        "floor_number",
    )
    op.drop_column(
        "properties",
        "carpet_area",
    )
    op.drop_column(
        "properties",
        "built_up_area",
    )
    op.drop_column(
        "properties",
        "bhk",
    )
    op.drop_column(
        "properties",
        "property_type",
    )
    op.drop_column(
        "properties",
        "postal_code",
    )
    op.drop_column(
        "properties",
        "state",
    )
    op.drop_column(
        "properties",
        "city",
    )
    op.drop_column(
        "properties",
        "locality",
    )
    op.drop_column(
        "properties",
        "address_line_2",
    )
    op.drop_column(
        "properties",
        "address_line_1",
    )