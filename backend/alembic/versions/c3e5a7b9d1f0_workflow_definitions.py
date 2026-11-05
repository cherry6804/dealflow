"""Workflow definitions, immutable versions, lifecycle history and the workflow permissions (DFR1-023).

Additive. Creates ``workflow_definitions``, ``workflow_versions`` and ``workflow_lifecycle_events``. A database trigger rejects any
UPDATE or DELETE of a published version, so immutability holds even for a direct database write. Registers workflows.read,
workflows.manage and workflows.publish and grants them to the system Owner role only. Downgrade refuses while workflow rows exist.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3e5a7b9d1f0"
down_revision: str | Sequence[str] | None = "b8d4f0a2c6e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("workflows.read", "View workflow definitions, versions and lifecycle history."),
    ("workflows.manage", "Create and edit workflow drafts and validate them."),
    ("workflows.publish", "Publish, pause, resume, roll back and archive workflows."),
)
WORKFLOW_TABLES = ("workflow_lifecycle_events", "workflow_versions", "workflow_definitions")


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("draft_configuration", sa.JSON(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_workflow_definitions_organization_name"),
        sa.CheckConstraint("status IN ('draft', 'published', 'paused', 'archived')", name="ck_workflow_definitions_status"),
    )
    op.create_index("ix_workflow_definitions_organization_id", "workflow_definitions", ["organization_id"])

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("agent_references", sa.JSON(), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workflow_id", "version_number", name="uq_workflow_versions_number"),
        sa.UniqueConstraint("id", "organization_id", name="uq_workflow_versions_id_organization"),
    )
    op.create_index("ix_workflow_versions_organization_workflow", "workflow_versions", ["organization_id", "workflow_id"])

    op.create_table(
        "workflow_lifecycle_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("target_version_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_workflow_lifecycle_events_workflow", "workflow_lifecycle_events",
                    ["organization_id", "workflow_id", "created_at"])

    # Published versions are immutable at the database level as well as in the service.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workflow_versions_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'workflow versions are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_workflow_versions_immutable
        BEFORE UPDATE OR DELETE ON workflow_versions
        FOR EACH ROW EXECUTE FUNCTION workflow_versions_immutable();
        """
    )

    connection = op.get_bind()
    for key, description in NEW_PERMISSIONS:
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
            JOIN permissions p ON p.key IN :keys
            WHERE r.name = 'DealFlow Owner' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT (SELECT COUNT(*) FROM workflow_definitions) + (SELECT COUNT(*) FROM workflow_versions)"
        " + (SELECT COUNT(*) FROM workflow_lifecycle_events)"
    )).scalar_one()
    if rows:
        raise RuntimeError("Workflow rows exist; downgrade would remove definitions, published versions and history.")
    op.execute("DROP TRIGGER IF EXISTS trg_workflow_versions_immutable ON workflow_versions")
    op.execute("DROP FUNCTION IF EXISTS workflow_versions_immutable()")
    for table in WORKFLOW_TABLES:
        op.drop_table(table)
    connection.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)")
        .bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
