
"""Persistent payment-provider webhook event model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BillingWebhookEvent(Base):
    """Track webhook delivery and processing state idempotently."""

    __tablename__ = "billing_webhook_events"

    STATUS_RECEIVED: ClassVar[str] = "RECEIVED"
    STATUS_PROCESSING: ClassVar[str] = "PROCESSING"
    STATUS_PROCESSED: ClassVar[str] = "PROCESSED"
    STATUS_FAILED: ClassVar[str] = "FAILED"

    STATUS_VALUES: ClassVar[tuple[str, ...]] = (
        STATUS_RECEIVED,
        STATUS_PROCESSING,
        STATUS_PROCESSED,
        STATUS_FAILED,
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_billing_webhook_events_provider_event",
        ),
        CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED')",
            name="ck_billing_webhook_events_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_billing_webhook_events_attempt_count",
        ),
        Index(
            "ix_billing_webhook_events_status_received",
            "status",
            "received_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    provider_event_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_RECEIVED,
        server_default=STATUS_RECEIVED,
    )

    attempt_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    def __init__(self, **kwargs: object) -> None:
        """Initialize Python defaults when constructing an instance."""
        kwargs.setdefault("status", self.STATUS_RECEIVED)
        kwargs.setdefault("attempt_count", 0)
        super().__init__(**kwargs)
