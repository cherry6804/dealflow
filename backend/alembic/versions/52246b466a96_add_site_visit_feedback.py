
"""Add customer feedback to site visits.

Revision ID: 52246b466a96
Revises: 54c638689803
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "52246b466a96"
down_revision: Union[str, Sequence[str], None] = "54c638689803"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a separate feedback field without changing existing notes."""
    op.add_column(
        "site_visits",
        sa.Column("feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove the feedback field."""
    op.drop_column("site_visits", "feedback")
