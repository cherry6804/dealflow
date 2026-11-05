"""Workflow executions, step records and the workflow run permission (DFR1-024).

Additive. Creates ``workflow_executions`` (each pinned to one immutable workflow version, with its trigger, state and outcome) and
``workflow_execution_steps`` (one record per step). Registers ``workflows.run`` and grants it to the system Owner role only. Downgrade
refuses while run rows exist, because they record what ran, what was approved and what was done.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f6b8c0e2a1"
down_revision: str | Sequence[str] | None = "c3e5a7b9d1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("workflows.run", "Start, cancel and retry workflow runs, and resume due timers."),
)


def upgrade() -> None:
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger_type", sa.String(length=10), nullable=False),
        sa.Column("trigger_event", sa.String(length=60), nullable=True),
        sa.Column("event_key", sa.String(length=200), nullable=True),
        sa.Column("source_execution_id", sa.Uuid(), nullable=True),
        sa.Column("retry_of_execution_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_values", sa.JSON(), nullable=False),
        sa.Column("run_as_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("initiated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("next_step_id", sa.String(length=40), nullable=True),
        sa.Column("steps_completed", sa.Integer(), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=80), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_executions_idempotency"),
        sa.UniqueConstraint("id", "organization_id", name="uq_workflow_executions_id_organization"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'waiting_timer', 'succeeded', 'failed', "
            "'cancelled', 'stopped', 'timed_out', 'dead_letter')",
            name="ck_workflow_executions_status",
        ),
        sa.CheckConstraint("trigger_type IN ('manual', 'event')", name="ck_workflow_executions_trigger"),
    )
    op.create_index("ix_workflow_executions_org_workflow_status", "workflow_executions",
                    ["organization_id", "workflow_id", "status"])
    op.create_index("ix_workflow_executions_org_created", "workflow_executions", ["organization_id", "created_at"])

    op.create_table(
        "workflow_execution_steps",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(length=40), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("execution_id", "step_id", name="uq_workflow_execution_steps_step"),
        sa.ForeignKeyConstraint(
            ["execution_id", "organization_id"],
            ["workflow_executions.id", "workflow_executions.organization_id"],
            name="fk_workflow_execution_steps_execution_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'waiting_approval', 'waiting_timer', 'cancelled')",
            name="ck_workflow_execution_steps_status",
        ),
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
        "SELECT (SELECT COUNT(*) FROM workflow_executions) + (SELECT COUNT(*) FROM workflow_execution_steps)"
    )).scalar_one()
    if rows:
        raise RuntimeError("Workflow run rows exist; downgrade would remove what ran and what was approved.")
    op.drop_table("workflow_execution_steps")
    op.drop_index("ix_workflow_executions_org_created", table_name="workflow_executions")
    op.drop_index("ix_workflow_executions_org_workflow_status", table_name="workflow_executions")
    op.drop_table("workflow_executions")
    connection.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)")
        .bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
