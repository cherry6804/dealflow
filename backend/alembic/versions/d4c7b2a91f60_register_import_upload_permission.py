"""Register the import upload permission.

Revision ID: d4c7b2a91f60
Revises: 8564215a0358
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4c7b2a91f60"
down_revision: str | Sequence[str] | None = "8564215a0358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Register imports.upload and grant it to the active owner role."""
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

    permission = connection.execute(
        sa.select(
            permissions.c.id,
            permissions.c.is_active,
        ).where(permissions.c.key == "imports.upload")
    ).mappings().first()

    if permission is None:
        permission_id = uuid.uuid4()
        connection.execute(
            permissions.insert().values(
                id=permission_id,
                key="imports.upload",
                description="Upload and preview contact import source files.",
                is_active=True,
            )
        )
        permission = {
            "id": permission_id,
            "is_active": True,
        }

    # Never grant an inactive permission or reactivate it implicitly.
    if not permission["is_active"]:
        return

    owner_role = connection.execute(
        sa.select(
            roles.c.id,
            roles.c.is_active,
        ).where(roles.c.name == "DealFlow Owner")
    ).mappings().first()

    # A fresh installation may not have created its owner role yet.
    if owner_role is None or not owner_role["is_active"]:
        return

    assignment_exists = connection.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == owner_role["id"],
            role_permissions.c.permission_id == permission["id"],
        )
    ).first()

    if assignment_exists is None:
        connection.execute(
            role_permissions.insert().values(
                id=uuid.uuid4(),
                role_id=owner_role["id"],
                permission_id=permission["id"],
            )
        )


def downgrade() -> None:
    """Preserve authorization data when reverting this data migration.

    The permission or assignment may have existed before this migration.
    Deleting either here could revoke legitimate access, so this migration
    deliberately leaves the data intact on downgrade.
    """
