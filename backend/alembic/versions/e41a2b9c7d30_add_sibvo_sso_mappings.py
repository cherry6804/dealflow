
"""Add explicit SIBVO identity and organization mappings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e41a2b9c7d30"
down_revision = "d2f4a6b8c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sibvo_identity_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "sibvo_subject",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "dealsflo_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dealsflo_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "sibvo_subject",
            name="uq_sibvo_identity_links_subject",
        ),
        sa.UniqueConstraint(
            "dealsflo_user_id",
            name="uq_sibvo_identity_links_dealsflo_user",
        ),
    )

    op.create_table(
        "sibvo_organization_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "sibvo_organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "dealsflo_organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dealsflo_organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "sibvo_organization_id",
            name="uq_sibvo_organization_links_sibvo_org",
        ),
        sa.UniqueConstraint(
            "dealsflo_organization_id",
            name="uq_sibvo_organization_links_dealsflo_org",
        ),
    )


def downgrade() -> None:
    op.drop_table("sibvo_organization_links")
    op.drop_table("sibvo_identity_links")
