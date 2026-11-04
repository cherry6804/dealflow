"""Reviewable PDF extraction per document (DFR1-035).

Additive. Creates ``document_reviews``: one current review per document, holding extracted values with page and source, the
review method, the gateway provider and model when one was used, the opening text and the stored title and author. Downgrade
drops the table. The rows are derived from the stored document, so dropping them loses no source data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1a5e7d9f3b4"
down_revision: str | Sequence[str] | None = "b9e4f2a7c1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("provider_key", sa.String(length=60), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("summary_page", sa.Integer(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", name="uq_document_reviews_document"),
    )
    op.create_index("ix_document_reviews_organization_id", "document_reviews", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_document_reviews_organization_id", table_name="document_reviews")
    op.drop_table("document_reviews")
