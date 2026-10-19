
"""Add notification preferences and authorization permissions.

Revision ID: 2199716b7a66
Revises: 4f6a91c2d830
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "2199716b7a66"
down_revision = "4f6a91c2d830"
branch_labels = None
depends_on = None


PREFERENCE_PERMISSIONS = (
    (
        "notifications.preferences.read",
        "Read the authenticated user's notification preferences.",
    ),
    (
        "notifications.preferences.update",
        "Update the authenticated user's notification preferences.",
    ),
)


def _register_preference_permissions() -> None:
    """Register preference permissions and grant them to active roles."""

    bind = op.get_bind()

    active_role_ids = bind.execute(
        text(
            """
            SELECT id
            FROM roles
            WHERE is_active IS TRUE
            """
        )
    ).scalars().all()

    for permission_key, description in PREFERENCE_PERMISSIONS:
        bind.execute(
            text(
                """
                INSERT INTO permissions (
                    id,
                    key,
                    description,
                    is_active
                )
                VALUES (
                    :id,
                    :key,
                    :description,
                    TRUE
                )
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "id": uuid4(),
                "key": permission_key,
                "description": description,
            },
        )

        permission = bind.execute(
            text(
                """
                SELECT id, is_active
                FROM permissions
                WHERE key = :key
                """
            ),
            {"key": permission_key},
        ).mappings().one()

        # Preserve an existing disabled permission.
        if not permission["is_active"]:
            continue

        permission_id = permission["id"]

        for role_id in active_role_ids:
            bind.execute(
                text(
                    """
                    INSERT INTO role_permissions (
                        id,
                        role_id,
                        permission_id
                    )
                    VALUES (
                        :id,
                        :role_id,
                        :permission_id
                    )
                    ON CONFLICT (role_id, permission_id) DO NOTHING
                    """
                ),
                {
                    "id": uuid4(),
                    "role_id": role_id,
                    "permission_id": permission_id,
                },
            )


def upgrade() -> None:
    """Create notification preferences and register permissions."""

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "follow_ups_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "deals_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "site_visits_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "leads_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "automation_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_notification_preferences_org_user",
        ),
    )

    _register_preference_permissions()


def downgrade() -> None:
    """Remove the notification preferences table."""

    # Preserve permission records, consistent with the migration convention.
    op.drop_table("notification_preferences")
