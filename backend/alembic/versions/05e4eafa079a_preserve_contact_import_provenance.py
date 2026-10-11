"""Preserve contact import provenance.

Revision ID: 05e4eafa079a
Revises: d4c7b2a91f60
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "05e4eafa079a"
down_revision: str | Sequence[str] | None = "d4c7b2a91f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tenant-safe import provenance to contacts."""
    op.create_unique_constraint(
        "uq_import_batches_id_organization_id",
        "import_batches",
        ["id", "organization_id"],
    )

    op.add_column(
        "contacts",
        sa.Column("import_batch_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("source_row_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_contacts_import_batch_id",
        "contacts",
        ["import_batch_id"],
        unique=False,
    )

    op.create_check_constraint(
        "ck_contacts_source_row_number_positive",
        "contacts",
        "source_row_number IS NULL OR source_row_number > 0",
    )

    op.create_check_constraint(
        "ck_contacts_import_provenance_complete",
        "contacts",
        "(import_batch_id IS NULL AND source_row_number IS NULL "
        "AND imported_at IS NULL) OR "
        "(import_batch_id IS NOT NULL AND source_row_number IS NOT NULL "
        "AND imported_at IS NOT NULL)",
    )

    op.create_foreign_key(
        "fk_contacts_import_batch_tenant",
        "contacts",
        "import_batches",
        ["import_batch_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove contact import provenance."""
    op.drop_constraint(
        "fk_contacts_import_batch_tenant",
        "contacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_contacts_import_provenance_complete",
        "contacts",
        type_="check",
    )
    op.drop_constraint(
        "ck_contacts_source_row_number_positive",
        "contacts",
        type_="check",
    )
    op.drop_index("ix_contacts_import_batch_id", table_name="contacts")

    op.drop_column("contacts", "imported_at")
    op.drop_column("contacts", "source_row_number")
    op.drop_column("contacts", "import_batch_id")

    op.drop_constraint(
        "uq_import_batches_id_organization_id",
        "import_batches",
        type_="unique",
    )