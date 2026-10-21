"""Register billing audit read permission.

Revision ID: 05f11754c0a9
Revises: b5259d9933c0
"""

from alembic import op
import sqlalchemy as sa
import uuid

revision = "05f11754c0a9"
down_revision = "b5259d9933c0"
branch_labels = None
depends_on = None

PERMISSION_KEY = "billing.audit.read"
PERMISSION_ID = uuid.UUID("05f11754-0000-4000-8000-000000000001")


def upgrade() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String(150)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO permissions (id, key, description, is_active)
            VALUES (:id, :key, :description, TRUE)
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {
            "id": PERMISSION_ID,
            "key": PERMISSION_KEY,
            "description": "Read billing reconciliation audit records.",
        },
    )


def downgrade() -> None:
    # Preserve permission records: roles may already reference this permission.
    pass