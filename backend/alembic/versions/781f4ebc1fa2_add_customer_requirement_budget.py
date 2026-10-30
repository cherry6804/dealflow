"""add customer requirement budget

Revision ID: 781f4ebc1fa2
Revises: 74e222ca4dab
Create Date: 2026-10-04 13:19:36.915366

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "781f4ebc1fa2"
down_revision: Union[str, Sequence[str], None] = "74e222ca4dab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "customer_requirements",
        sa.Column(
            "budget_min",
            sa.Numeric(precision=18, scale=2),
            nullable=True,
        ),
    )
    op.add_column(
        "customer_requirements",
        sa.Column(
            "budget_max",
            sa.Numeric(precision=18, scale=2),
            nullable=True,
        ),
    )
    op.add_column(
        "customer_requirements",
        sa.Column(
            "budget_currency",
            sa.String(length=3),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(
        "customer_requirements",
        "budget_currency",
    )
    op.drop_column(
        "customer_requirements",
        "budget_max",
    )
    op.drop_column(
        "customer_requirements",
        "budget_min",
    )