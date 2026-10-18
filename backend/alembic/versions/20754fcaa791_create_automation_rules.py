
"""Create tenant-scoped automation rules and register permissions."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20754fcaa791"
down_revision: str | Sequence[str] | None = "d91a6c3e8b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create automation rules and register their permissions."""
    op.create_table(
        "automation_rules",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=150),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "trigger_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "trigger_config",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "conditions",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "actions",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            nullable=True,
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
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'DISABLED')",
            name="ck_automation_rules_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_automation_rules_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_automation_rules_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_automation_rules_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_automation_rules_organization_id",
        "automation_rules",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_automation_rules_org_status",
        "automation_rules",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_automation_rules_org_created",
        "automation_rules",
        ["organization_id", "created_at"],
        unique=False,
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

    definitions = (
        (
            "automation.read",
            "View automation rules in the active organization.",
        ),
        (
            "automation.create",
            "Create automation rules in the active organization.",
        ),
        (
            "automation.update",
            "Update, activate, and disable automation rules in the active organization.",
        ),
    )

    owner_role = connection.execute(
        sa.select(roles.c.id, roles.c.is_active).where(
            roles.c.name == "DealFlow Owner"
        )
    ).mappings().first()

    for key, description in definitions:
        permission = connection.execute(
            sa.select(
                permissions.c.id,
                permissions.c.is_active,
            ).where(permissions.c.key == key)
        ).mappings().first()

        if permission is None:
            permission_id = uuid.uuid4()
            connection.execute(
                permissions.insert().values(
                    id=permission_id,
                    key=key,
                    description=description,
                    is_active=True,
                )
            )
            permission = {
                "id": permission_id,
                "is_active": True,
            }

        # Do not implicitly reactivate a disabled permission.
        if not permission["is_active"]:
            continue

        if owner_role is None or not owner_role["is_active"]:
            continue

        assignment = connection.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == owner_role["id"],
                role_permissions.c.permission_id == permission["id"],
            )
        ).first()

        if assignment is None:
            connection.execute(
                role_permissions.insert().values(
                    id=uuid.uuid4(),
                    role_id=owner_role["id"],
                    permission_id=permission["id"],
                )
            )


def downgrade() -> None:
    """Remove the automation rules table but preserve authorization records."""
    op.drop_index(
        "ix_automation_rules_org_created",
        table_name="automation_rules",
    )
    op.drop_index(
        "ix_automation_rules_org_status",
        table_name="automation_rules",
    )
    op.drop_index(
        "ix_automation_rules_organization_id",
        table_name="automation_rules",
    )
    op.drop_table("automation_rules")
