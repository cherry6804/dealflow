
"""Add organization-scoped roles and protected system roles."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d8e7a42b90"
down_revision: Union[str, Sequence[str], None] = "b7e4c2d91a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "roles",
        sa.Column(
            "organization_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.add_column(
        "roles",
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_foreign_key(
        "fk_roles_organization_id",
        "roles",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_roles_organization_id",
        "roles",
        ["organization_id"],
        unique=False,
    )

    # Preserve all existing role IDs and references.
    op.drop_index("ix_roles_name", table_name="roles")

    # Global roles remain globally unique. Tenant roles can reuse a name
    # in another organization but cannot duplicate names within their own.
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_roles_global_name",
            "roles",
            [sa.text("lower(name)")],
            unique=True,
            postgresql_where=sa.text("organization_id IS NULL"),
        )
        op.create_index(
            "uq_roles_organization_name",
            "roles",
            ["organization_id", sa.text("lower(name)")],
            unique=True,
            postgresql_where=sa.text("organization_id IS NOT NULL"),
        )
    else:
        # Portable fallback; use case-sensitive uniqueness on other dialects.
        op.create_index(
            "uq_roles_global_name",
            "roles",
            ["name"],
            unique=True,
        )
        op.create_index(
            "uq_roles_organization_name",
            "roles",
            ["organization_id", "name"],
            unique=True,
        )

    # The existing owner role stays global and is marked protected.
    op.execute(
        sa.text(
            """
            UPDATE roles
            SET is_system = TRUE
            WHERE lower(trim(name)) = 'dealflow owner'
              AND organization_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("uq_roles_organization_name", table_name="roles")
    op.drop_index("uq_roles_global_name", table_name="roles")

    op.create_index(
        "ix_roles_name",
        "roles",
        ["name"],
        unique=True,
    )

    op.drop_index("ix_roles_organization_id", table_name="roles")
    op.drop_constraint(
        "fk_roles_organization_id",
        "roles",
        type_="foreignkey",
    )
    op.drop_column("roles", "is_system")
    op.drop_column("roles", "organization_id")
