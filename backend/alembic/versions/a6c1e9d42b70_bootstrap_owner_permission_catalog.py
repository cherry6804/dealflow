
"""Register canonical DealFlow permissions and bootstrap the owner role."""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "a6c1e9d42b70"
down_revision: str | Sequence[str] | None = "f9418b6a9fd7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep this snapshot self-contained; do not import application code in migrations.
PERMISSIONS = (
    ("contacts.create", "Create contacts"),
    ("contacts.read", "View contacts"),
    ("contacts.update", "Update contacts"),
    ("leads.create", "Create leads"),
    ("leads.read", "View leads"),
    ("leads.update", "Update leads"),
    ("properties.create", "Create properties"),
    ("properties.read", "View properties"),
    ("properties.update", "Update properties"),
    ("requirements.create", "Create requirements"),
    ("requirements.read", "View requirements"),
    ("requirements.update", "Update requirements"),
    ("imports.upload", "Upload data imports"),
    ("deals.create", "Create deals"),
    ("deals.read", "View deals"),
    ("deals.update", "Update deals"),
    ("deal_negotiations.read", "View deal negotiations"),
    ("deal_negotiations.update", "Update deal negotiations"),
    ("payment_milestones.read", "View payment milestones"),
    ("payment_milestones.create", "Create payment milestones"),
    ("payment_milestones.update", "Update payment milestones"),
    ("commission.read", "View deal commissions"),
    ("commission.create", "Create deal commissions"),
    ("commission.update", "Update deal commissions"),
    ("referrals.read", "View referrals"),
    ("referrals.create", "Create referrals"),
    ("referrals.update", "Update referrals"),
    ("documents.read", "View documents"),
    ("documents.upload", "Upload documents"),
    ("documents.download", "Download documents"),
    ("documents.manage", "Manage documents"),
    ("automation.read", "View automation rules"),
    ("automation.create", "Create automation rules"),
    ("automation.update", "Update automation rules"),
    ("billing.audit.read", "View billing audit records"),
    ("notifications.preferences.read", "View notification preferences"),
    ("notifications.preferences.update", "Update notification preferences"),
)


def upgrade() -> None:
    connection = op.get_bind()

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(100)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String(150)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )

    owner = connection.execute(
        sa.select(roles.c.id, roles.c.is_active).where(
            roles.c.name == "DealFlow Owner"
        )
    ).first()

    if owner is None:
        owner_id = uuid.uuid4()
        connection.execute(
            roles.insert().values(
                id=owner_id,
                name="DealFlow Owner",
                description="Workspace owner role for DealFlow organizations.",
                is_active=True,
            )
        )
    else:
        owner_id = owner.id
        if not owner.is_active:
            raise RuntimeError(
                "Cannot bootstrap permissions: DealFlow Owner role is inactive."
            )

    permission_ids: dict[str, uuid.UUID] = {}

    for key, description in PERMISSIONS:
        existing = connection.execute(
            sa.select(
                permissions.c.id,
                permissions.c.is_active,
            ).where(permissions.c.key == key)
        ).first()

        if existing is None:
            permission_id = uuid.uuid4()
            connection.execute(
                permissions.insert().values(
                    id=permission_id,
                    key=key,
                    description=description,
                    is_active=True,
                )
            )
            permission_ids[key] = permission_id
        else:
            # Preserve existing IDs, descriptions and active/disabled states.
            permission_ids[key] = existing.id

    for key, permission_id in permission_ids.items():
        active = connection.execute(
            sa.select(permissions.c.is_active).where(
                permissions.c.id == permission_id
            )
        ).scalar_one()

        # Do not grant permissions that have been intentionally disabled.
        if not active:
            continue

        assignment_exists = connection.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == owner_id,
                role_permissions.c.permission_id == permission_id,
            )
        ).first()

        if assignment_exists is None:
            connection.execute(
                role_permissions.insert().values(
                    id=uuid.uuid4(),
                    role_id=owner_id,
                    permission_id=permission_id,
                )
            )


def downgrade() -> None:
    # Keep roles, permissions and assignments intact on downgrade.
    # Removing them could break existing memberships or authorization.
    pass
