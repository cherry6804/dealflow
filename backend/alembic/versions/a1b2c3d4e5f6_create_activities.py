
"""Create business activities for lead timelines."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d747d390d684"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the activities table."""
    op.create_table(
        "activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_activities_organization",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            ondelete="CASCADE",
            name="fk_activities_lead_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            ondelete="RESTRICT",
            name="fk_activities_actor_membership_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_activities_id_organization_id",
        ),
    )

    op.create_index(
        "ix_activities_org_lead_occurred_at",
        "activities",
        ["organization_id", "lead_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_activities_org_occurred_at",
        "activities",
        ["organization_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_activities_actor_occurred_at",
        "activities",
        ["actor_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the activities table."""
    op.drop_index(
        "ix_activities_actor_occurred_at",
        table_name="activities",
    )
    op.drop_index(
        "ix_activities_org_occurred_at",
        table_name="activities",
    )
    op.drop_index(
        "ix_activities_org_lead_occurred_at",
        table_name="activities",
    )
    op.drop_table("activities")
