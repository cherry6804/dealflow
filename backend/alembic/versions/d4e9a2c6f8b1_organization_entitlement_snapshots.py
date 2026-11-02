"""Organization-level SIBVO entitlement snapshot cache (E12 WS5, ADR-0027).

Additive. One row per organization and product. The downgrade drops the table only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e9a2c6f8b1"
down_revision: str | Sequence[str] | None = "c3d8f1a9e2b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_entitlement_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_key", sa.String(length=40), nullable=False),
        sa.Column("snapshot_body", sa.JSON(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_refresh_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "failure_count >= 0",
            name="ck_org_entitlement_snapshots_failures_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_entitlement_snapshots_organization_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization_entitlement_snapshots"),
        sa.UniqueConstraint(
            "organization_id",
            "product_key",
            name="uq_org_entitlement_snapshots_org_product",
        ),
    )


def downgrade() -> None:
    op.drop_table("organization_entitlement_snapshots")
