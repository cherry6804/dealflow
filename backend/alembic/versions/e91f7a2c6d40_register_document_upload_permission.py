
"""Register the document upload permission.

Revision ID: e91f7a2c6d40
Revises: b26da4a49547
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e91f7a2c6d40"
down_revision: str | Sequence[str] | None = "b26da4a49547"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Register documents.upload and grant it to the active owner role."""
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
        ).where(permissions.c.key == "documents.upload")
    ).mappings().first()

    if permission is None:
        permission_id = uuid.uuid4()
        connection.execute(
            permissions.insert().values(
                id=permission_id,
                key="documents.upload",
                description="Upload business documents to the verified organization.",
                is_active=True,
            )
        )
        permission = {"id": permission_id, "is_active": True}

    # Do not implicitly reactivate an existing disabled permission.
    if not permission["is_active"]:
        return

    owner_role = connection.execute(
        sa.select(roles.c.id, roles.c.is_active).where(
            roles.c.name == "DealFlow Owner"
        )
    ).mappings().first()

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
    """Preserve authorization data when reverting this data migration."""
