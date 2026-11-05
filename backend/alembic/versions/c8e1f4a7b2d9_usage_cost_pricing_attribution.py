"""Provider pricing versions, provider cost entries and workflow attribution columns (DFR1-017).

Additive. Creates ``ai_provider_prices`` (platform price versions, no seeded rates) and ``ai_provider_cost_entries`` (one cost entry
per settled usage unit, priced or unpriced, never customer credits). Adds nullable ``workflow_step_id`` to ``ai_usage_events`` and
nullable ``workflow_execution_id`` and ``workflow_step_id`` to ``agent_executions``. Existing rows keep null in every new column.
Downgrade refuses while price or cost rows exist, because they record what was charged and at which version.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8e1f4a7b2d9"
down_revision: str | Sequence[str] | None = "f1a7c3e9b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_prices",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("quantity_per_price", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_reference", sa.String(length=200), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "unit_price_minor >= 0", name="ck_ai_provider_prices_price_non_negative"
        ),
        sa.CheckConstraint(
            "quantity_per_price >= 1", name="ck_ai_provider_prices_quantity_positive"
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_ai_provider_prices_version_positive"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_ai_provider_prices_validity_order",
        ),
        sa.UniqueConstraint(
            "provider_key",
            "model",
            "unit",
            "version",
            name="uq_ai_provider_prices_version",
        ),
    )
    op.create_index(
        "uq_ai_provider_prices_open",
        "ai_provider_prices",
        ["provider_key", "model", "unit"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    op.create_table(
        "ai_provider_cost_entries",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "usage_event_id",
            sa.Uuid(),
            sa.ForeignKey("ai_usage_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "price_id",
            sa.Uuid(),
            sa.ForeignKey("ai_provider_prices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("price_version", sa.Integer(), nullable=True),
        sa.Column("unit_price_minor", sa.Integer(), nullable=True),
        sa.Column("quantity_per_price", sa.Integer(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('priced', 'unpriced')",
            name="ck_ai_provider_cost_entries_status",
        ),
        sa.CheckConstraint(
            "quantity >= 0", name="ck_ai_provider_cost_entries_quantity"
        ),
        sa.CheckConstraint(
            "(status = 'priced' AND amount_minor IS NOT NULL AND amount_minor >= 0 AND currency IS NOT NULL"
            " AND price_id IS NOT NULL AND price_version IS NOT NULL)"
            " OR (status = 'unpriced' AND amount_minor IS NULL AND reason_code IS NOT NULL)",
            name="ck_ai_provider_cost_entries_state",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_ai_provider_cost_entries_idempotency",
        ),
    )
    op.create_index(
        "ix_ai_provider_cost_entries_org_occurred",
        "ai_provider_cost_entries",
        ["organization_id", "occurred_at"],
    )

    op.add_column(
        "ai_usage_events",
        sa.Column("workflow_step_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "agent_executions", sa.Column("workflow_execution_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "agent_executions",
        sa.Column("workflow_step_id", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM ai_provider_prices) + (SELECT COUNT(*) FROM ai_provider_cost_entries)"
        )
    ).scalar_one()
    if rows:
        raise RuntimeError(
            "Provider price or cost rows exist; downgrade would remove what was charged and at which version."
        )
    op.drop_column("agent_executions", "workflow_step_id")
    op.drop_column("agent_executions", "workflow_execution_id")
    op.drop_column("ai_usage_events", "workflow_step_id")
    op.drop_index(
        "ix_ai_provider_cost_entries_org_occurred",
        table_name="ai_provider_cost_entries",
    )
    op.drop_table("ai_provider_cost_entries")
    op.drop_index("uq_ai_provider_prices_open", table_name="ai_provider_prices")
    op.drop_table("ai_provider_prices")
