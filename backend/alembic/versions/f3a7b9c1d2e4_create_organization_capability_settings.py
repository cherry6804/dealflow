"""Create organization capability settings and governance permissions (DFR1-006).

Capabilities are disabled by default. Organizations that exist before this migration
had deal-created automation running, so their automation master switch is recorded as
enabled (policy version 1, no actor) to preserve behaviour. Every organization created
after this migration starts with no row, which means disabled.

Downgrade removes the table and only the permission rows this migration added.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a7b9c1d2e4"
down_revision: str | Sequence[str] | None = "a1e2c3d4f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GOVERNANCE_PERMISSIONS = (
    ("governance.capabilities.read", "View AI and automation capability settings."),
    ("governance.capabilities.manage", "Change AI and automation capability settings."),
)


def upgrade() -> None:
    op.create_table(
        "organization_capability_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("capability_key", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "capability_key",
            name="uq_organization_capability_settings_org_key",
        ),
    )
    op.create_index(
        "ix_organization_capability_settings_organization_id",
        "organization_capability_settings",
        ["organization_id"],
    )

    # Preserve the existing deal-created automation behaviour for organizations that
    # already exist. Newly created organizations get no row and therefore stay disabled.
    op.execute(
        sa.text(
            """
            INSERT INTO organization_capability_settings
                (id, organization_id, capability_key, is_enabled, policy_version,
                 updated_by_user_id, created_at, updated_at)
            SELECT gen_random_uuid(), o.id, 'automation.master', true, 1, NULL, now(), now()
            FROM organizations o
            """
        )
    )

    connection = op.get_bind()
    for key, description in GOVERNANCE_PERMISSIONS:
        connection.execute(
            sa.text(
                """
                INSERT INTO permissions (id, key, description, is_active, created_at, updated_at)
                SELECT gen_random_uuid(), CAST(:key AS VARCHAR), CAST(:description AS VARCHAR), true, now(), now()
                WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE key = CAST(:key AS VARCHAR))
                """
            ),
            {"key": key, "description": description},
        )

    # Owner receives both keys. Admin receives read only; manage is owner-only.
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key IN ('governance.capabilities.read', 'governance.capabilities.manage')
            WHERE r.name = 'DealFlow Owner' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key = 'governance.capabilities.read'
            WHERE r.name = 'Admin' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    changed_by_people = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM organization_capability_settings WHERE updated_by_user_id IS NOT NULL"
        )
    ).scalar_one()
    if changed_by_people:
        raise RuntimeError(
            "Refusing to drop organization_capability_settings: people have changed capability "
            "switches. Export the table before downgrading."
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions
                WHERE key IN ('governance.capabilities.read', 'governance.capabilities.manage')
            )
            """
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM permissions WHERE key IN "
            "('governance.capabilities.read', 'governance.capabilities.manage')"
        )
    )
    op.drop_index(
        "ix_organization_capability_settings_organization_id",
        table_name="organization_capability_settings",
    )
    op.drop_table("organization_capability_settings")
