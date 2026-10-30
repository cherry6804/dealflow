"""Create retention policies, legal holds and privacy requests with permissions (DFR1-050).

No data is deleted or exported by this migration. Retention and legal hold tables start
empty. Downgrade drops the three tables and removes only the permission rows this
migration adds. Privacy request rows are not removed by an automatic process.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h5c9d1e3f6a7"
down_revision: str | Sequence[str] | None = "g4b8c0d2e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIVACY_PERMISSIONS = (
    ("governance.privacy.read", "View retention policies, legal holds and privacy requests."),
    ("governance.privacy.manage", "Change retention, legal holds and privacy requests."),
)


def upgrade() -> None:
    op.create_table(
        "privacy_retention_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category_key", sa.String(length=100), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("changed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "category_key", "version",
            name="uq_privacy_retention_policies_org_category_version",
        ),
    )
    op.create_index("ix_privacy_retention_policies_organization_id", "privacy_retention_policies", ["organization_id"])

    op.create_table(
        "privacy_legal_holds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category_key", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("placed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("released_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_privacy_legal_holds_organization_id", "privacy_legal_holds", ["organization_id"])
    op.create_index("ix_privacy_legal_holds_org_category", "privacy_legal_holds", ["organization_id", "category_key"])

    op.create_table(
        "privacy_data_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("categories", sa.Text(), nullable=False),
        sa.Column("decisions", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("artifact_reference", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_privacy_data_requests_organization_id", "privacy_data_requests", ["organization_id"])

    connection = op.get_bind()
    for key, description in PRIVACY_PERMISSIONS:
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
            JOIN permissions p ON p.key IN ('governance.privacy.read', 'governance.privacy.manage')
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
            JOIN permissions p ON p.key = 'governance.privacy.read'
            WHERE r.name = 'Admin' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions WHERE permission_id IN (
                SELECT id FROM permissions WHERE key IN ('governance.privacy.read', 'governance.privacy.manage')
            )
            """
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM permissions WHERE key IN ('governance.privacy.read', 'governance.privacy.manage')"
        )
    )
    op.drop_index("ix_privacy_data_requests_organization_id", table_name="privacy_data_requests")
    op.drop_table("privacy_data_requests")
    op.drop_index("ix_privacy_legal_holds_org_category", table_name="privacy_legal_holds")
    op.drop_index("ix_privacy_legal_holds_organization_id", table_name="privacy_legal_holds")
    op.drop_table("privacy_legal_holds")
    op.drop_index("ix_privacy_retention_policies_organization_id", table_name="privacy_retention_policies")
    op.drop_table("privacy_retention_policies")
