"""Human tasks, their append-only history and the human task permission (DFR1-025).

Additive. Creates ``human_tasks`` (one approval task per gated workflow step, bound to one governance approval record) and
``human_task_events`` (the append-only history). The history table refuses UPDATE and DELETE through a trigger, as the workflow
versions table does. Registers ``human_tasks.manage`` and grants it to the system Owner role only. Downgrade refuses while task rows
exist, because they record who was asked, who decided and what was decided.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a7c9d1f3b2"
down_revision: str | Sequence[str] | None = "d4f6b8c0e2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("human_tasks.manage", "Assign, cancel and expire human tasks."),
)

IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION human_task_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'human task events are immutable';
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.create_table(
        "human_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("required_permission", sa.String(length=64), nullable=False),
        sa.Column("assigned_to_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), sa.ForeignKey("approval_requests.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_step_id", sa.String(length=40), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.String(length=1000), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "workflow_execution_id", "workflow_step_id",
                            name="uq_human_tasks_execution_step"),
        sa.UniqueConstraint("approval_request_id", name="uq_human_tasks_approval_request"),
        sa.UniqueConstraint("id", "organization_id", name="uq_human_tasks_id_organization"),
        sa.CheckConstraint("kind IN ('approval')", name="ck_human_tasks_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_human_tasks_status",
        ),
    )
    op.create_index("ix_human_tasks_org_status_due", "human_tasks", ["organization_id", "status", "due_at"])

    op.create_table(
        "human_task_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("human_tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("from_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("to_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'assigned', 'reassigned', 'comment', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_human_task_events_type",
        ),
    )
    op.create_index("ix_human_task_events_task", "human_task_events", ["organization_id", "task_id", "created_at"])
    op.execute(IMMUTABLE_FUNCTION)
    op.execute("DROP TRIGGER IF EXISTS trg_human_task_events_immutable ON human_task_events")
    op.execute(
        "CREATE TRIGGER trg_human_task_events_immutable BEFORE UPDATE OR DELETE ON human_task_events "
        "FOR EACH ROW EXECUTE FUNCTION human_task_events_immutable()"
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
        "SELECT (SELECT COUNT(*) FROM human_tasks) + (SELECT COUNT(*) FROM human_task_events)"
    )).scalar_one()
    if rows:
        raise RuntimeError("Human task rows exist; downgrade would remove who was asked and what was decided.")
    op.execute("DROP TRIGGER IF EXISTS trg_human_task_events_immutable ON human_task_events")
    op.execute("DROP FUNCTION IF EXISTS human_task_events_immutable()")
    op.drop_index("ix_human_task_events_task", table_name="human_task_events")
    op.drop_table("human_task_events")
    op.drop_index("ix_human_tasks_org_status_due", table_name="human_tasks")
    op.drop_table("human_tasks")
    connection.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)")
        .bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
