
"""Add secure team invitations and team-management permissions."""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "b7e4c2d91a60"
down_revision: str | Sequence[str] | None = "a6c1e9d42b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = (
    ("organization.members.read", "View organization team members"),
    ("organization.members.manage", "Manage organization memberships and roles"),
    ("organization.invites.manage", "Create, resend, and revoke team invitations"),
)


def upgrade() -> None:
    op.create_table(
        "team_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_team_invitations_token_hash"),
    )

    op.create_index(
        "ix_team_invitations_org_status",
        "team_invitations",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_team_invitations_email_org",
        "team_invitations",
        ["organization_id", "email"],
    )

    connection = op.get_bind()

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String(150)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(100)),
        sa.column("is_active", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )

    permission_ids: dict[str, uuid.UUID] = {}

    for key, description in PERMISSIONS:
        existing = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.key == key)
        ).first()

        if existing:
            permission_ids[key] = existing.id
            continue

        permission_id = uuid.uuid4()
        connection.execute(
            permissions.insert().values(
                id=permission_id,
                key=key,
                description=description,
                is_active=True,
            )
        )
        permission_ids[key] = permission_id

    owner = connection.execute(
        sa.select(roles.c.id, roles.c.is_active).where(
            roles.c.name == "DealFlow Owner"
        )
    ).first()

    if owner is None or not owner.is_active:
        raise RuntimeError(
            "Cannot register team permissions: active DealFlow Owner role is required."
        )

    for permission_id in permission_ids.values():
        is_active = connection.execute(
            sa.select(permissions.c.is_active).where(
                permissions.c.id == permission_id
            )
        ).scalar_one()

        if not is_active:
            continue

        existing_assignment = connection.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == owner.id,
                role_permissions.c.permission_id == permission_id,
            )
        ).first()

        if existing_assignment is None:
            connection.execute(
                role_permissions.insert().values(
                    id=uuid.uuid4(),
                    role_id=owner.id,
                    permission_id=permission_id,
                )
            )


def downgrade() -> None:
    # Retain the permission catalog and assignments to avoid removing
    # authorization records that may have been used by existing data.
    op.drop_index(
        "ix_team_invitations_email_org",
        table_name="team_invitations",
    )
    op.drop_index(
        "ix_team_invitations_org_status",
        table_name="team_invitations",
    )
    op.drop_table("team_invitations")
