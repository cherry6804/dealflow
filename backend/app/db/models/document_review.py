"""Reviewable extraction of one PDF document (DFR1-035).

One current review per document. It holds the values found by the labelled-line rules, each with its page and the line it came
from, the opening text of the first page, and the title and author stored in the file. It is derived data: it is removed when
its source document is deleted, and the review API also checks that the document is still available.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentReview(Base):
    __tablename__ = "document_reviews"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_document_reviews_document"),
        Index("ix_document_reviews_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fields: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
