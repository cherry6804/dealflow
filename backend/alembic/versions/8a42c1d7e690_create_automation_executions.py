
"""Create tenant-scoped automation execution records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a42c1d7e690"
down_revision: str | Sequence[str] | None = "20754fcaa791"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create automation execution tracking."""

    # PostgreSQL requires a unique constraint on the exact referenced
    # column combination used by the composite foreign key.
    op.create_unique_constraint(
        "uq_automation_rules_id_organization",
        "automation_rules",
        ["id", "organization_id"],
    )

    op.create_table(
        "automation_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("action_results", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN "
            "('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'SKIPPED')",
            name="ck_automation_executions_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_automation_executions_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "organization_id"],
            ["automation_rules.id", "automation_rules.organization_id"],
            name="fk_automation_execution_rule_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_automation_executions_id_organization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "rule_id",
            "event_type",
            "event_id",
            name="uq_automation_execution_event_rule",
        ),
    )

    op.create_index(
        "ix_automation_executions_org_created",
        "automation_executions",
        ["organization_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_automation_executions_org_status",
        "automation_executions",
        ["organization_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove automation execution tracking."""

    op.drop_index(
        "ix_automation_executions_org_status",
        table_name="automation_executions",
    )

    op.drop_index(
        "ix_automation_executions_org_created",
        table_name="automation_executions",
    )

    op.drop_table("automation_executions")

    op.drop_constraint(
        "uq_automation_rules_id_organization",
        "automation_rules",
        type_="unique",
    )
