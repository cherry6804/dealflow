
"""Create requirement property shortlists.

Revision ID: b7d108a1cafe
Revises: 0c2573f34423
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d108a1cafe"
down_revision: Union[str, Sequence[str], None] = "0c2573f34423"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tenant-scoped requirement property shortlists."""
    op.create_table(
        "requirement_property_shortlists",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("customer_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_requirement_property_shortlists_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            ["customer_requirements.id", "customer_requirements.organization_id"],
            name="fk_requirement_property_shortlists_requirement_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name="fk_requirement_property_shortlists_property",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_requirement_property_shortlists_creator_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "customer_requirement_id",
            "property_id",
            name="uq_requirement_property_shortlists_requirement_property",
        ),
    )
    op.create_index(
        "ix_requirement_property_shortlists_org_requirement_created",
        "requirement_property_shortlists",
        ["organization_id", "customer_requirement_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_requirement_property_shortlists_org_property",
        "requirement_property_shortlists",
        ["organization_id", "property_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove requirement property shortlists."""
    op.drop_index(
        "ix_requirement_property_shortlists_org_property",
        table_name="requirement_property_shortlists",
    )
    op.drop_index(
        "ix_requirement_property_shortlists_org_requirement_created",
        table_name="requirement_property_shortlists",
    )
    op.drop_table("requirement_property_shortlists")
