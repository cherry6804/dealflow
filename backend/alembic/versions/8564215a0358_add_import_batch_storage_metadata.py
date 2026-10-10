"""Add import batch storage metadata.

Revision ID: 8564215a0358
Revises: 96348ac0352e
Create Date: 2026-10-10 11:41:10.724040
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision: str = "8564215a0358"
down_revision: Union[str, Sequence[str], None] = "96348ac0352e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add private storage metadata to import batches."""
    op.add_column(
        "import_batches",
        sa.Column(
            "storage_backend",
            sa.String(length=30),
            nullable=True,
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column(
            "storage_key",
            sa.String(length=512),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_import_batches_storage_key",
        "import_batches",
        ["storage_key"],
    )


def downgrade() -> None:
    """Remove private storage metadata from import batches."""
    op.drop_constraint(
        "uq_import_batches_storage_key",
        "import_batches",
        type_="unique",
    )
    op.drop_column("import_batches", "storage_key")
    op.drop_column("import_batches", "storage_backend")