"""add property source and owner association

Revision ID: d66f07ec1ef7
Revises: c7a58611822c
Create Date: 2026-10-08 23:08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d66f07ec1ef7"
down_revision: Union[str, Sequence[str], None] = "c7a58611822c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add tenant-safe Property source and owner associations."""
    op.add_column(
        "properties",
        sa.Column(
            "source_contact_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.add_column(
        "properties",
        sa.Column(
            "owner_contact_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_properties_source_contact_tenant",
        "properties",
        "contacts",
        ["source_contact_id", "organization_id"],
        ["id", "organization_id"],
    )

    op.create_foreign_key(
        "fk_properties_owner_contact_tenant",
        "properties",
        "contacts",
        ["owner_contact_id", "organization_id"],
        ["id", "organization_id"],
    )


def downgrade() -> None:
    """Remove tenant-safe Property source and owner associations."""
    op.drop_constraint(
        "fk_properties_owner_contact_tenant",
        "properties",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_properties_source_contact_tenant",
        "properties",
        type_="foreignkey",
    )

    op.drop_column(
        "properties",
        "owner_contact_id",
    )

    op.drop_column(
        "properties",
        "source_contact_id",
    )