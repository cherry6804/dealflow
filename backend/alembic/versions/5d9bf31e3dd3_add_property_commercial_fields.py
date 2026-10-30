"""add property commercial fields

Revision ID: 5d9bf31e3dd3
Revises: 5dd0d5e5aebd
Create Date: 2026-10-08 00:03:40.749112

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5d9bf31e3dd3"
down_revision: Union[str, Sequence[str], None] = "5dd0d5e5aebd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "properties",
        sa.Column(
            "transaction_type",
            sa.String(length=20),
            nullable=True,
        ),
    )

    op.add_column(
        "properties",
        sa.Column(
            "price",
            sa.Numeric(precision=20, scale=2),
            nullable=True,
        ),
    )

    op.add_column(
        "properties",
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=True,
        ),
    )

    op.add_column(
        "properties",
        sa.Column(
            "rent",
            sa.Numeric(precision=20, scale=2),
            nullable=True,
        ),
    )

    op.add_column(
        "properties",
        sa.Column(
            "security_deposit",
            sa.Numeric(precision=20, scale=2),
            nullable=True,
        ),
    )

    op.add_column(
        "properties",
        sa.Column(
            "maintenance_charge",
            sa.Numeric(precision=20, scale=2),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column("properties", "maintenance_charge")
    op.drop_column("properties", "security_deposit")
    op.drop_column("properties", "rent")
    op.drop_column("properties", "currency")
    op.drop_column("properties", "price")
    op.drop_column("properties", "transaction_type")