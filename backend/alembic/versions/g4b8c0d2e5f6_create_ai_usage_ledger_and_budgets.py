"""Create the AI usage ledger, organization usage budgets and their permissions (DFR1-017).

The ledger and budgets start empty. No provider usage is backfilled. Budgets are not
configured for any organization by this migration, so billable AI work stays refused
until an owner sets a budget.

Downgrade drops both tables and removes only the permission rows this migration adds.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g4b8c0d2e5f6"
down_revision: str | Sequence[str] | None = "f3a7b9c1d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USAGE_PERMISSIONS = (
    ("governance.usage.read", "View AI usage, budgets and provider cost."),
    ("governance.budgets.manage", "Set organization AI usage budgets."),
)


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("reserved_quantity", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("task_type", sa.String(length=80), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("agent_id", sa.String(length=120), nullable=True),
        sa.Column("workflow_id", sa.String(length=120), nullable=True),
        sa.Column("execution_id", sa.String(length=120), nullable=True),
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_ai_usage_events_org_idempotency"),
    )
    op.create_index("ix_ai_usage_events_organization_id", "ai_usage_events", ["organization_id"])
    op.create_index("ix_ai_usage_events_org_occurred", "ai_usage_events", ["organization_id", "occurred_at"])

    op.create_table(
        "organization_usage_budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("limit_quantity", sa.BigInteger(), nullable=False),
        sa.Column("reserved_quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("consumed_quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_alert_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "unit", "period_start",
            name="uq_organization_usage_budgets_org_unit_period",
        ),
    )
    op.create_index("ix_organization_usage_budgets_organization_id", "organization_usage_budgets", ["organization_id"])

    connection = op.get_bind()
    for key, description in USAGE_PERMISSIONS:
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
    # Owner receives both keys. Admin receives usage read only.
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key IN ('governance.usage.read', 'governance.budgets.manage')
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
            JOIN permissions p ON p.key = 'governance.usage.read'
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
                SELECT id FROM permissions WHERE key IN ('governance.usage.read', 'governance.budgets.manage')
            )
            """
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM permissions WHERE key IN ('governance.usage.read', 'governance.budgets.manage')"
        )
    )
    op.drop_index("ix_organization_usage_budgets_organization_id", table_name="organization_usage_budgets")
    op.drop_table("organization_usage_budgets")
    op.drop_index("ix_ai_usage_events_org_occurred", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_organization_id", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
