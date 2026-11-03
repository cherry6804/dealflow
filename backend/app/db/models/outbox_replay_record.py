"""Audit record for an operator replay of a dead-lettered outbox event (WS3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxReplayRecord(Base):
    """One controlled re-queue of a dead letter.

    Written in the same transaction that moves the event back to ``pending``, so a replay
    exists if and only if the event was re-queued. The record keeps the state the operator
    replayed from, so the history of a dead letter can be reconstructed.
    """

    __tablename__ = "outbox_replay_records"
    __table_args__ = (
        Index("ix_outbox_replay_records_event", "event_id"),
        Index("ix_outbox_replay_records_organization_requested", "organization_id", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("outbox_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operator: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_dead_letter_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
