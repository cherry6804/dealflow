"""Agent definitions, versions, executions and steps, and the agent permissions (DFR1-019).

Additive. Creates ``agents``, ``agent_versions`` (immutable once written), ``agent_executions`` and ``agent_execution_steps``. Registers
five permissions (agents.read, agents.manage, agents.publish, agents.run, agents.approve) and grants them to the system Owner role
only. Other roles receive nothing automatically. Downgrade refuses while agent rows exist, because they record published
configurations and execution history.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2a8c4f1b9d7"
down_revision: str | Sequence[str] | None = "d2b6f8a1c4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("agents.read", "View agent definitions, versions and executions."),
    ("agents.manage", "Create and edit agent drafts."),
    ("agents.publish", "Publish, pause, resume, roll back and archive agents."),
    ("agents.run", "Start an agent execution."),
    ("agents.approve", "Approve or reject an agent's approval step."),
)
AGENT_TABLES = ("agent_execution_steps", "agent_executions", "agent_versions", "agents")


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("draft_configuration", sa.JSON(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "name", name="uq_agents_organization_name"),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"])

    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("validation_snapshot", sa.JSON(), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_number"),
    )
    op.create_index("ix_agent_versions_organization_id", "agent_versions", ["organization_id"])

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("initiated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_values", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("next_step_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("steps_completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.String(length=80), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_executions_org_idempotency"),
    )
    op.create_index("ix_agent_executions_agent_status", "agent_executions", ["agent_id", "status"])
    op.create_index("ix_agent_executions_organization_created", "agent_executions", ["organization_id", "created_at"])

    op.create_table(
        "agent_execution_steps",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("agent_executions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("execution_id", "step_index", name="uq_agent_execution_steps_index"),
    )
    op.create_index("ix_agent_execution_steps_organization_id", "agent_execution_steps", ["organization_id"])

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
        "SELECT (SELECT COUNT(*) FROM agents) + (SELECT COUNT(*) FROM agent_executions)"
    )).scalar_one()
    if rows:
        raise RuntimeError("Agent rows exist; downgrade would remove published configurations and execution history.")
    keys = [key for key, _ in NEW_PERMISSIONS]
    connection.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)")
        .bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": keys},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": keys},
    )
    op.drop_index("ix_agent_execution_steps_organization_id", table_name="agent_execution_steps")
    op.drop_table("agent_execution_steps")
    op.drop_index("ix_agent_executions_organization_created", table_name="agent_executions")
    op.drop_index("ix_agent_executions_agent_status", table_name="agent_executions")
    op.drop_table("agent_executions")
    op.drop_index("ix_agent_versions_organization_id", table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_index("ix_agents_organization_id", table_name="agents")
    op.drop_table("agents")
