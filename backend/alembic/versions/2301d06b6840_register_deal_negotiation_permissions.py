
"""Register deal negotiation permissions."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2301d06b6840"
down_revision: str = "cbedb9dc7bb1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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

    definitions = (
        (
            "deal_negotiations.read",
            "View negotiation states and history in the active organization.",
        ),
        (
            "deal_negotiations.update",
            "Create and update negotiation states in the active organization.",
        ),
    )

    owner_role = connection.execute(
        sa.select(roles.c.id, roles.c.is_active).where(
            roles.c.name == "DealFlow Owner"
        )
    ).mappings().first()

    for key, description in definitions:
        permission = connection.execute(
            sa.select(permissions.c.id, permissions.c.is_active).where(
                permissions.c.key == key
            )
        ).mappings().first()

        if permission is None:
            permission_id = uuid.uuid4()
            connection.execute(
                permissions.insert().values(
                    id=permission_id,
                    key=key,
                    description=description,
                    is_active=True,
                )
            )
            permission = {"id": permission_id, "is_active": True}

        if not permission["is_active"]:
            continue

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
    # Preserve authorization records and assignments on downgrade.
    pass
