
"""Seed the shared DealFlow Owner role."""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "8b41d6f20c73"
down_revision: str | Sequence[str] | None = "7a2c9e4d61b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ensure the shared owner role exists without replacing existing data."""
    connection = op.get_bind()

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(100)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )

    existing = connection.execute(
        sa.select(roles.c.id).where(
            roles.c.name == "DealFlow Owner"
        )
    ).first()

    if existing is None:
        connection.execute(
            roles.insert().values(
                id=uuid.uuid4(),
                name="DealFlow Owner",
                description="Workspace owner role for DealFlow organizations.",
                is_active=True,
            )
        )


def downgrade() -> None:
    """Preserve the shared role because memberships may depend on it."""
    pass
