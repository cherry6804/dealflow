
"""Backfill active permissions for the DealFlow Owner role."""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "c6a9d2e41f70"
down_revision: str | Sequence[str] | None = "8b41d6f20c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Assign existing active permissions to the active owner role."""
    connection = op.get_bind()

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(100)),
        sa.column("is_active", sa.Boolean()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("is_active", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )

    owner_role = connection.execute(
        sa.select(roles.c.id).where(
            roles.c.name == "DealFlow Owner",
            roles.c.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if owner_role is None:
        raise RuntimeError(
            "Cannot backfill permissions: active DealFlow Owner role is missing."
        )

    active_permission_ids = connection.execute(
        sa.select(permissions.c.id).where(
            permissions.c.is_active.is_(True)
        )
    ).scalars()

    for permission_id in active_permission_ids:
        existing = connection.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == owner_role,
                role_permissions.c.permission_id == permission_id,
            )
        ).first()

        if existing is None:
            connection.execute(
                role_permissions.insert().values(
                    id=uuid.uuid4(),
                    role_id=owner_role,
                    permission_id=permission_id,
                )
            )


def downgrade() -> None:
    """Preserve authorization assignments on downgrade."""
    pass
