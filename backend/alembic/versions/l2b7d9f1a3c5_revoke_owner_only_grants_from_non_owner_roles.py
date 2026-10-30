"""Revoke owner-only permission grants from non-owner roles (E13 hardening).

Owner-only permission keys were defined in code, but the Admin template and any custom role
could still receive them. This migration removes those grants from every role except the system
Owner role. The removed rows are copied to a backup table first, so a downgrade restores the
exact previous state.

Impact: any member whose access depended on an owner-only key through a non-owner role loses
that access. Owners keep it. The removed grants are listed in the backup table, so the impact can
be reviewed before a downgrade is considered.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l2b7d9f1a3c5"
down_revision: str | Sequence[str] | None = "k1a6c8e0f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Hardcoded on purpose: this migration must not change if application code changes later.
OWNER_ONLY_KEYS = (
    "organization.roles.manage",
    "billing.audit.read",
    "governance.capabilities.manage",
    "governance.budgets.manage",
    "governance.privacy.manage",
    "provider_credentials.manage",
)
BACKUP_TABLE = "role_permission_revocations_l2b7"

_NON_OWNER_OWNER_ONLY_GRANTS = f"""
    FROM role_permissions rp
    JOIN permissions p ON p.id = rp.permission_id
    JOIN roles r ON r.id = rp.role_id
    WHERE p.key IN ({", ".join(f"'{key}'" for key in OWNER_ONLY_KEYS)})
      AND NOT (r.is_system = true AND r.name = 'DealFlow Owner')
"""


def upgrade() -> None:
    op.create_table(
        BACKUP_TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("permission_id", sa.Uuid(), sa.ForeignKey("permissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"INSERT INTO {BACKUP_TABLE} (id, role_id, permission_id, original_created_at, revoked_at) "
            f"SELECT gen_random_uuid(), rp.role_id, rp.permission_id, rp.created_at, now() "
            f"{_NON_OWNER_OWNER_ONLY_GRANTS}"
        )
    )
    connection.execute(
        sa.text(
            f"DELETE FROM role_permissions rp USING permissions p, roles r "
            f"WHERE p.id = rp.permission_id AND r.id = rp.role_id "
            f"AND p.key IN ({', '.join(f"'{key}'" for key in OWNER_ONLY_KEYS)}) "
            f"AND NOT (r.is_system = true AND r.name = 'DealFlow Owner')"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"INSERT INTO role_permissions (id, role_id, permission_id, created_at) "
            f"SELECT gen_random_uuid(), b.role_id, b.permission_id, b.original_created_at "
            f"FROM {BACKUP_TABLE} b "
            f"WHERE NOT EXISTS (SELECT 1 FROM role_permissions rp "
            f"WHERE rp.role_id = b.role_id AND rp.permission_id = b.permission_id)"
        )
    )
    op.drop_table(BACKUP_TABLE)
