"""Bind SSO sessions to the organization authorized by SIBVO."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f5b7c9d1e3a4"
down_revision = "e41a2b9c7d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_auth_sessions_organization_id_organizations",
        "auth_sessions",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_auth_sessions_organization_id",
        "auth_sessions",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_sessions_organization_id",
        table_name="auth_sessions",
    )
    op.drop_constraint(
        "fk_auth_sessions_organization_id_organizations",
        "auth_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_sessions", "organization_id")
