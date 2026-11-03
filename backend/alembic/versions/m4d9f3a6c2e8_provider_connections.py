"""Provider connection registry and permissions (DFR1-006 / DFR1-011 foundation).

Additive. Creates ``provider_connections`` (metadata and secret references only). Permissions:
``governance.providers.read`` for the Admin and DealFlow Owner roles, and ``governance.providers.manage``
for DealFlow Owner. Downgrade refuses while connections exist, because they are the record of what an
organization configured.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m4d9f3a6c2e8"
down_revision: str | Sequence[str] | None = "l3c8e2f5a1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVIDER_PERMISSIONS = (
    ("governance.providers.read", "View provider connections and their verification status."),
    ("governance.providers.manage", "Register, verify and disable provider connections."),
)


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_kind", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("secret_ref", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="not_verified"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "provider_kind", name="uq_provider_connections_org_kind"),
        sa.CheckConstraint(
            "provider_kind IN ('llm', 'whatsapp', 'email', 'voice')",
            name="ck_provider_connections_kind",
        ),
        sa.CheckConstraint(
            "status IN ('not_verified', 'verified', 'unhealthy', 'disabled')",
            name="ck_provider_connections_status",
        ),
    )
    op.create_index("ix_provider_connections_organization_id", "provider_connections", ["organization_id"])
    op.create_index(
        "ix_provider_connections_org_status", "provider_connections", ["organization_id", "status"]
    )

    connection = op.get_bind()
    for key, description in PROVIDER_PERMISSIONS:
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
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key IN ('governance.providers.read', 'governance.providers.manage')
            WHERE r.name = 'DealFlow Owner' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
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
            JOIN permissions p ON p.key = 'governance.providers.read'
            WHERE r.name = 'Admin' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(sa.text("SELECT COUNT(*) FROM provider_connections")).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade: provider connections exist. They record what an organization configured."
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions WHERE permission_id IN (
                SELECT id FROM permissions WHERE key IN ('governance.providers.read', 'governance.providers.manage')
            )
            """
        )
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN ('governance.providers.read', 'governance.providers.manage')")
    )
    op.drop_index("ix_provider_connections_org_status", table_name="provider_connections")
    op.drop_index("ix_provider_connections_organization_id", table_name="provider_connections")
    op.drop_table("provider_connections")
