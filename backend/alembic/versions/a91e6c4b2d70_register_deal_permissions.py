"""Register deal permissions.

Revision ID: a91e6c4b2d70
Revises: 7f4d9c2e1a63
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "a91e6c4b2d70"
down_revision: str | Sequence[str] | None = "7f4d9c2e1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Register deal permissions and grant them to the active owner role.

    Offline SQL generation cannot inspect existing permission or role data.
    The data-dependent migration therefore runs only with a live connection.
    """
    if context.is_offline_mode():
        return

    connection = op.get_bind()

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String(150)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(100)),
        sa.column("is_active", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )

    permission_definitions = (
        ("deals.create", "Create deals in the active organization."),
        ("deals.read", "View deals in the active organization."),
    )

    owner_role = connection.execute(
        sa.select(roles.c.id, roles.c.is_active).where(
            roles.c.name == "DealFlow Owner"
        )
    ).mappings().first()

    for permission_key, description in permission_definitions:
        permission = connection.execute(
            sa.select(
                permissions.c.id,
                permissions.c.is_active,
            ).where(permissions.c.key == permission_key)
        ).mappings().first()

        if permission is None:
            permission_id = uuid.uuid4()
            connection.execute(
                permissions.insert().values(
                    id=permission_id,
                    key=permission_key,
                    description=description,
                    is_active=True,
                )
            )
            permission = {
                "id": permission_id,
                "is_active": True,
            }

        # Never grant an inactive permission.
        if not permission["is_active"]:
            continue

        # A fresh installation may not yet have an owner role.
        if owner_role is None or not owner_role["is_active"]:
            continue

        existing = connection.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == owner_role["id"],
                role_permissions.c.permission_id == permission["id"],
            )
        ).first()

        if existing is None:
            connection.execute(
                role_permissions.insert().values(
                    id=uuid.uuid4(),
                    role_id=owner_role["id"],
                    permission_id=permission["id"],
                )
            )


def downgrade() -> None:
    """Preserve authorization records and assignments on downgrade."""
    pass
