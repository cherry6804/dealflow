"""Create encrypted provider credentials and their permissions (DFR1-011 subset for DFR1-015).

The table stores only authenticated ciphertext and the key metadata needed to decrypt it. A
check constraint keeps active rows encrypted and revoked rows empty. A partial unique index
allows one active credential per organization and provider.

Owners receive the provider credential permissions. Downgrade refuses while any credential row
exists, because dropping the table would discard encrypted secrets without revoking them.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k1a6c8e0f2b4"
down_revision: str | Sequence[str] | None = "i7f2c9d4e1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVIDER_CREDENTIAL_PERMISSIONS = (
    ("provider_credentials.read", "View provider credential metadata."),
    ("provider_credentials.manage", "Create, rotate and revoke provider credentials."),
)


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ciphertext", sa.Text(), nullable=True),
        sa.Column("encryption_key_id", sa.String(length=64), nullable=True),
        sa.Column("encryption_algorithm", sa.String(length=40), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("rotated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_provider_credentials_status"),
        sa.CheckConstraint(
            "(status = 'active' AND ciphertext IS NOT NULL"
            " AND encryption_key_id IS NOT NULL AND encryption_algorithm IS NOT NULL)"
            " OR (status = 'revoked' AND ciphertext IS NULL)",
            name="ck_provider_credentials_secret_state",
        ),
    )
    op.create_index(
        "ix_provider_credentials_organization_id",
        "provider_credentials",
        ["organization_id"],
    )
    op.create_index(
        "uq_provider_credentials_active_provider",
        "provider_credentials",
        ["organization_id", "provider_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    connection = op.get_bind()
    for key, description in PROVIDER_CREDENTIAL_PERMISSIONS:
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
            JOIN permissions p ON p.key IN ('provider_credentials.read', 'provider_credentials.manage')
            WHERE r.name = 'DealFlow Owner' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    stored = connection.execute(sa.text("SELECT COUNT(*) FROM provider_credentials")).scalar_one()
    if stored:
        raise RuntimeError(
            "Refusing to drop provider_credentials: encrypted provider credentials exist. "
            "Revoke them, and export the table if it must be kept, before downgrading."
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions
                WHERE key IN ('provider_credentials.read', 'provider_credentials.manage')
            )
            """
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM permissions WHERE key IN ('provider_credentials.read', 'provider_credentials.manage')"
        )
    )
    op.drop_index("uq_provider_credentials_active_provider", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_organization_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
