"""add requirement match and shortlist history

Revision ID: 46683ea97897
Revises: b7d108a1cafe
Create Date: 2026-10-15 14:35:15.280157
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers used by Alembic.
revision: str = "46683ea97897"
down_revision: Union[str, Sequence[str], None] = "b7d108a1cafe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create immutable requirement matching and shortlist history."""

    op.create_table(
        "requirement_match_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        # Historical reference only. Intentionally no requirement FK.
        sa.Column("customer_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criteria_snapshot", sa.JSON(), nullable=False),
        sa.Column("total_candidates", sa.Integer(), nullable=False),
        sa.Column("matched_candidates", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_requirement_match_runs_actor_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_requirement_match_runs_id_organization",
        ),
    )

    op.create_index(
        "ix_requirement_match_runs_org_requirement_created",
        "requirement_match_runs",
        ["organization_id", "customer_requirement_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "requirement_shortlist_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        # Historical reference only. Intentionally no requirement FK.
        sa.Column("customer_requirement_id", sa.Uuid(), nullable=False),
        # Historical reference only. Intentionally no property FK.
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("property_snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('ADDED', 'REMOVED')",
            name="ck_requirement_shortlist_events_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_requirement_shortlist_events_actor_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_requirement_shortlist_events_org_requirement_created",
        "requirement_shortlist_events",
        ["organization_id", "customer_requirement_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "requirement_match_run_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        # Historical reference only. Intentionally no property FK.
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("overall_match", sa.Boolean(), nullable=False),
        sa.Column("property_snapshot", sa.JSON(), nullable=False),
        sa.Column("criteria_results_snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_run_id", "organization_id"],
            [
                "requirement_match_runs.id",
                "requirement_match_runs.organization_id",
            ],
            name="fk_requirement_match_run_results_run_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "match_run_id",
            "property_id",
            name="uq_requirement_match_run_results_run_property",
        ),
    )

    op.create_index(
        "ix_requirement_match_run_results_org_run",
        "requirement_match_run_results",
        ["organization_id", "match_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove DF-109 history tables and their indexes."""

    op.drop_index(
        "ix_requirement_match_run_results_org_run",
        table_name="requirement_match_run_results",
    )
    op.drop_table("requirement_match_run_results")

    op.drop_index(
        "ix_requirement_shortlist_events_org_requirement_created",
        table_name="requirement_shortlist_events",
    )
    op.drop_table("requirement_shortlist_events")

    op.drop_index(
        "ix_requirement_match_runs_org_requirement_created",
        table_name="requirement_match_runs",
    )
    op.drop_table("requirement_match_runs")