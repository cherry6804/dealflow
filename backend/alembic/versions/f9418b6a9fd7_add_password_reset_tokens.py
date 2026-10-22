
"""add password reset tokens

Revision ID: f9418b6a9fd7
Revises: d84e2a7b19c3
Create Date: 2026-10-23 02:06:24.595693
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers used by Alembic.
revision: str = "f9418b6a9fd7"
down_revision: Union[str, Sequence[str], None] = "d84e2a7b19c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create password-reset token storage."""
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_password_reset_tokens_expires_at"),
        "password_reset_tokens",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_password_reset_tokens_token_hash"),
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"),
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove password-reset token storage."""
    op.drop_index(
        op.f("ix_password_reset_tokens_user_id"),
        table_name="password_reset_tokens",
    )
    op.drop_index(
        op.f("ix_password_reset_tokens_token_hash"),
        table_name="password_reset_tokens",
    )
    op.drop_index(
        op.f("ix_password_reset_tokens_expires_at"),
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
