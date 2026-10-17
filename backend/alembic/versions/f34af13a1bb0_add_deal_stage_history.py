"""add deal stage history

Revision ID: f34af13a1bb0
Revises: 2301d06b6840
Create Date: 2026-10-17 17:28:26.236573

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f34af13a1bb0"
down_revision: Union[str, Sequence[str], None] = "2301d06b6840"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create deal stage history with tenant-consistent deal references."""
    op.create_table(
        "deal_stage_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("from_stage", sa.String(length=30), nullable=False),
        sa.Column("to_stage", sa.String(length=30), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_deal_stage_history_deal_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_deal_stage_history_org_deal_created",
        "deal_stage_history",
        ["organization_id", "deal_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop deal stage history."""
    op.drop_index(
        "ix_deal_stage_history_org_deal_created",
        table_name="deal_stage_history",
    )
    op.drop_table("deal_stage_history")
