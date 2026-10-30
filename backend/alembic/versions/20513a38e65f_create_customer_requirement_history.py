"""create customer requirement history

Revision ID: 20513a38e65f
Revises: 84118e9b69c2
Create Date: 2026-10-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20513a38e65f"
down_revision: Union[str, Sequence[str], None] = "84118e9b69c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "customer_requirement_history",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "customer_requirement_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "change_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "snapshot",
            sa.JSON(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            [
                "customer_requirements.id",
                "customer_requirements.organization_id",
            ],
            name="fk_customer_requirement_history_requirement_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_customer_requirement_history_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_customer_requirement_history_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_requirement_id",
            "organization_id",
            "version",
            name="uq_customer_requirement_history_requirement_org_version",
        ),
    )

    op.create_index(
        op.f("ix_customer_requirement_history_customer_requirement_id"),
        "customer_requirement_history",
        ["customer_requirement_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_customer_requirement_history_organization_id"),
        "customer_requirement_history",
        ["organization_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_customer_requirement_history_actor_id"),
        "customer_requirement_history",
        ["actor_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_customer_requirement_history_occurred_at"),
        "customer_requirement_history",
        ["occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_customer_requirement_history_occurred_at"),
        table_name="customer_requirement_history",
    )

    op.drop_index(
        op.f("ix_customer_requirement_history_actor_id"),
        table_name="customer_requirement_history",
    )

    op.drop_index(
        op.f("ix_customer_requirement_history_organization_id"),
        table_name="customer_requirement_history",
    )

    op.drop_index(
        op.f("ix_customer_requirement_history_customer_requirement_id"),
        table_name="customer_requirement_history",
    )

    op.drop_table("customer_requirement_history")