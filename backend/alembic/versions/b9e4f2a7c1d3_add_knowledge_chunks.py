"""Derived knowledge chunks and embeddings (DFR1-016).

Additive. Creates ``knowledge_chunks``: bounded text pieces of available documents, with the embedding returned by the AI
gateway. No pgvector column: the extension is not installed on the test server, so similarity is computed in the application.
Downgrade drops the table. The rows are derived copies of document text, so dropping them loses no source data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9e4f2a7c1d3"
down_revision: str | Sequence[str] | None = "f7c3a9d1e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
    )
    op.create_index("ix_knowledge_chunks_organization_id", "knowledge_chunks", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_organization_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
