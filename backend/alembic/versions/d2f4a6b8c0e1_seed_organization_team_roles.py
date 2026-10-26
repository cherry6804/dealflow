
"""Seed organization-scoped team roles and migrate legacy Owner assignments.

Revision ID: d2f4a6b8c0e1
Revises: c1d8e7a42b90
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "d2f4a6b8c0e1"
down_revision = "c1d8e7a42b90"
branch_labels = None
depends_on = None


ROLE_TEMPLATES: dict[str, tuple[str, str]] = {
    "DealFlow Owner": (
        "Full administrative access to this organization.",
        "owner",
    ),
    "Admin": (
        "Manage day-to-day organization operations and team access.",
        "admin",
    ),
    "Manager": (
        "Manage operational records and team workflows.",
        "manager",
    ),
    "Member": (
        "Create and update standard business records.",
        "member",
    ),
    "Viewer": (
        "Read-only access to standard business records.",
        "viewer",
    ),
}

NEW_PERMISSION = (
    "organization.roles.manage",
    "Create and manage organization-scoped custom roles.",
)

RECORD_PREFIXES = (
    "contacts.",
    "leads.",
    "properties.",
    "requirements.",
    "deals.",
    "deal_negotiations.",
    "payment_milestones.",
    "commission.",
    "referrals.",
    "documents.",
)

VIEWER_SUFFIXES = (".read", ".view", ".list")

OWNER_ONLY_KEYS = {
    "organization.roles.manage",
    "billing.audit.read",
}

BATCH_SIZE = 1000


def _chunks(
    items: list[dict[str, Any]],
    size: int = BATCH_SIZE,
) -> Iterable[list[dict[str, Any]]]:
    """Yield bounded batches to keep bulk operations manageable."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _permission_keys_for_role(name: str, keys: set[str]) -> set[str]:
    """Build default grants from the active permission catalogue."""
    if name == "DealFlow Owner":
        return set(keys)

    if name == "Admin":
        return keys - OWNER_ONLY_KEYS

    if name == "Manager":
        return {
            key
            for key in keys
            if key.startswith(RECORD_PREFIXES)
            and key.endswith(
                (
                    ".read",
                    ".create",
                    ".update",
                    ".manage",
                    ".complete",
                    ".reschedule",
                )
            )
        } | {
            key
            for key in keys
            if key in {
                "organization.members.read",
                "organization.invites.manage",
            }
        }

    if name == "Member":
        return {
            key
            for key in keys
            if key.startswith(RECORD_PREFIXES)
            and key.endswith((".read", ".create", ".update"))
        }

    if name == "Viewer":
        return {
            key
            for key in keys
            if key.startswith(RECORD_PREFIXES)
            and key.endswith(VIEWER_SUFFIXES)
        }

    return set()


def upgrade() -> None:
    bind = op.get_bind()

    # Keep the migration bounded if the database is unexpectedly blocked.
    # The migration remains transactional under Alembic.
    bind.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
    bind.execute(sa.text("SET LOCAL statement_timeout = '10min'"))

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )

    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )

    # ------------------------------------------------------------------
    # 1. Ensure organization.roles.manage exists and is active.
    # ------------------------------------------------------------------
    manage_row = bind.execute(
        sa.select(permissions.c.id, permissions.c.is_active).where(
            permissions.c.key == NEW_PERMISSION[0]
        )
    ).one_or_none()

    if manage_row is None:
        manage_permission_id = uuid.uuid4()
        bind.execute(
            permissions.insert().values(
                id=manage_permission_id,
                key=NEW_PERMISSION[0],
                description=NEW_PERMISSION[1],
                is_active=True,
            )
        )
    else:
        manage_permission_id, is_active = manage_row
        if not is_active:
            bind.execute(
                permissions.update()
                .where(permissions.c.id == manage_permission_id)
                .values(
                    description=NEW_PERMISSION[1],
                    is_active=True,
                )
            )

    # ------------------------------------------------------------------
    # 2. Load the active permission catalogue once.
    # ------------------------------------------------------------------
    permission_rows = bind.execute(
        sa.select(permissions.c.id, permissions.c.key).where(
            permissions.c.is_active.is_(True)
        )
    ).all()

    permission_id_by_key = {
        row.key: row.id for row in permission_rows
    }
    permission_keys = set(permission_id_by_key)

    # ------------------------------------------------------------------
    # 3. Load organizations and existing scoped roles once.
    # ------------------------------------------------------------------
    organization_ids = bind.execute(
        sa.text("SELECT id FROM organizations")
    ).scalars().all()

    existing_role_rows = bind.execute(
        sa.select(
            roles.c.id,
            roles.c.organization_id,
            roles.c.name,
        ).where(roles.c.organization_id.is_not(None))
    ).all()

    # Key by organization ID and case-insensitive role name.
    role_id_by_org_and_name: dict[tuple[uuid.UUID, str], uuid.UUID] = {
        (row.organization_id, row.name.lower()): row.id
        for row in existing_role_rows
    }

    # ------------------------------------------------------------------
    # 4. Prepare missing roles in memory and insert in batches.
    # ------------------------------------------------------------------
    missing_roles: list[dict[str, Any]] = []
    role_updates: list[uuid.UUID] = []

    for organization_id in organization_ids:
        for role_name, (description, _template) in ROLE_TEMPLATES.items():
            role_key = (organization_id, role_name.lower())

            if role_key in role_id_by_org_and_name:
                role_updates.append(role_id_by_org_and_name[role_key])
                continue

            role_id = uuid.uuid4()
            role_id_by_org_and_name[role_key] = role_id

            missing_roles.append(
                {
                    "id": role_id,
                    "name": role_name,
                    "organization_id": organization_id,
                    "description": description,
                    "is_system": True,
                    "is_active": True,
                }
            )

    # Preserve existing IDs; protect and reactivate existing default roles.
    for role_id in role_updates:
        bind.execute(
            roles.update()
            .where(roles.c.id == role_id)
            .values(is_system=True, is_active=True)
        )

    for batch in _chunks(missing_roles):
        bind.execute(roles.insert(), batch)

    # ------------------------------------------------------------------
    # 5. Load current permission assignments once.
    # ------------------------------------------------------------------
    existing_pairs = {
        (row.role_id, row.permission_id)
        for row in bind.execute(
            sa.select(
                role_permissions.c.role_id,
                role_permissions.c.permission_id,
            )
        ).all()
    }

    # ------------------------------------------------------------------
    # 6. Build all missing grants and insert them in bounded batches.
    # ------------------------------------------------------------------
    missing_assignments: list[dict[str, Any]] = []

    for organization_id in organization_ids:
        for role_name in ROLE_TEMPLATES:
            role_id = role_id_by_org_and_name[
                (organization_id, role_name.lower())
            ]

            for permission_key in _permission_keys_for_role(
                role_name,
                permission_keys,
            ):
                permission_id = permission_id_by_key.get(permission_key)

                if permission_id is None:
                    continue

                pair = (role_id, permission_id)
                if pair in existing_pairs:
                    continue

                existing_pairs.add(pair)
                missing_assignments.append(
                    {
                        "id": uuid.uuid4(),
                        "role_id": role_id,
                        "permission_id": permission_id,
                    }
                )

    # Use PostgreSQL ON CONFLICT as an additional safeguard against
    # duplicate role-permission pairs.
    insert_assignment = sa.text(
        """
        INSERT INTO role_permissions (id, role_id, permission_id)
        VALUES (:id, :role_id, :permission_id)
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
    )

    for batch in _chunks(missing_assignments):
        bind.execute(insert_assignment, batch)

    # ------------------------------------------------------------------
    # 7. Migrate legacy global Owner assignments in set-based SQL.
    #
    # First remove legacy assignments only where the same membership
    # already has the target organization-scoped Owner assignment.
    # Then update the remaining legacy assignments in one statement.
    # ------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            DELETE FROM membership_roles AS legacy_assignment
            USING organization_memberships AS membership,
                  roles AS legacy_role,
                  roles AS scoped_owner
            WHERE legacy_assignment.membership_id = membership.id
              AND legacy_assignment.role_id = legacy_role.id
              AND legacy_role.organization_id IS NULL
              AND lower(legacy_role.name) = 'dealflow owner'
              AND scoped_owner.organization_id = membership.organization_id
              AND lower(scoped_owner.name) = 'dealflow owner'
              AND EXISTS (
                  SELECT 1
                  FROM membership_roles AS existing_assignment
                  WHERE existing_assignment.membership_id = membership.id
                    AND existing_assignment.role_id = scoped_owner.id
              )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE membership_roles AS assignment
            SET role_id = scoped_owner.id
            FROM organization_memberships AS membership,
                 roles AS legacy_role,
                 roles AS scoped_owner
            WHERE assignment.membership_id = membership.id
              AND assignment.role_id = legacy_role.id
              AND legacy_role.organization_id IS NULL
              AND lower(legacy_role.name) = 'dealflow owner'
              AND scoped_owner.organization_id = membership.organization_id
              AND lower(scoped_owner.name) = 'dealflow owner'
              AND NOT EXISTS (
                  SELECT 1
                  FROM membership_roles AS existing_assignment
                  WHERE existing_assignment.membership_id = membership.id
                    AND existing_assignment.role_id = scoped_owner.id
              )
            """
        )
    )


def downgrade() -> None:
    # Intentionally non-destructive. These organization roles and
    # membership assignments may already have been used by the application.
    pass
