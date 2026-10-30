"""Add customer requirement status indexes.

Revision ID: d747d390d684
Revises: 05e4eafa079a
"""

from collections.abc import Sequence

from alembic import op


revision: str = "d747d390d684"
down_revision: str | Sequence[str] | None = "05e4eafa079a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add indexes for customer requirement filtering."""
    op.create_index(
        "ix_customer_requirements_is_active",
        "customer_requirements",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_customer_requirements_status",
        "customer_requirements",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove customer requirement filtering indexes."""
    op.drop_index(
        "ix_customer_requirements_status",
        table_name="customer_requirements",
    )
    op.drop_index(
        "ix_customer_requirements_is_active",
        table_name="customer_requirements",
    )