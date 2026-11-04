"""Organization-level AI task routes (DFR1-015).

Additive. Creates ``ai_task_routes``: one row per organization and task type, naming the provider and model. It stores no
credential. No permission is added. Downgrade drops the table, which discards the configured routes (the table holds
configuration only, no evidence record).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7c3a9d1e5b2"
down_revision: str | Sequence[str] | None = "n5e8a1c4d7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_task_routes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("task", sa.String(length=20), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("fallback_provider_key", sa.String(length=40), nullable=True),
        sa.Column("fallback_model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "task", name="uq_ai_task_routes_org_task"),
        sa.CheckConstraint(
            "task IN ('text', 'embedding', 'speech', 'multimodal')",
            name="ck_ai_task_routes_task",
        ),
        sa.CheckConstraint(
            "(fallback_provider_key IS NULL) = (fallback_model IS NULL)",
            name="ck_ai_task_routes_fallback_pair",
        ),
    )
    op.create_index("ix_ai_task_routes_organization_id", "ai_task_routes", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_task_routes_organization_id", table_name="ai_task_routes")
    op.drop_table("ai_task_routes")
