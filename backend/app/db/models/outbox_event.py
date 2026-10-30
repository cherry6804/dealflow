"""Transactional outbox: domain events written in the same transaction as the change."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxEvent(Base):
    """One domain event awaiting dispatch to its handler.

    Rows are inserted in the caller's database transaction, so an event exists
    if and only if the business change it describes committed. Dispatch is
    at-least-once: a handler may run again after a crash, so handlers must be
    idempotent. The idempotency key is unique across the table, which lets
    producers retry an enqueue without creating duplicate events.
    """

    __tablename__ = "outbox_events"

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_DELIVERED = "delivered"
    STATUS_DEAD_LETTER = "dead_letter"
    STATUSES = (
        STATUS_PENDING,
        STATUS_PROCESSING,
        STATUS_DELIVERED,
        STATUS_DEAD_LETTER,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'dead_letter')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts_non_negative"),
        CheckConstraint(
            "max_attempts >= 1",
            name="ck_outbox_events_max_attempts_positive",
        ),
        Index("ix_outbox_events_dispatch", "status", "available_at"),
        Index("ix_outbox_events_organization_created", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
