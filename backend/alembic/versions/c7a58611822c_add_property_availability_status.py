"""add property availability status

Revision ID: c7a58611822c
Revises: 086f4ae72a3f
Create Date: 2026-10-08 21:08:01.899767

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7a58611822c"
down_revision: Union[str, Sequence[str], None] = "086f4ae72a3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "properties",
        sa.Column("status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("properties", "status")