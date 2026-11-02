"""Idempotent AI usage ledger entry (DFR1-017).

Each row is one billable or metered quantity for one organization. Provider cost and
customer credit consumption are separate units. A row is created as a reservation before
billable work, then settled to the actual quantity, released, or recorded directly when
usage arrives after the fact. A row is never edited to hide a correction; a reversal is
a status change that keeps the original quantity visible.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Reasons stored in ``released_reason`` when a reservation leaves the RESERVED state.
RELEASE_REASON_RELEASED = "released"
RELEASE_REASON_EXPIRED = "expired"


class AiUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_ai_usage_events_org_idempotency",
        ),
        Index("ix_ai_usage_events_org_occurred", "organization_id", "occurred_at"),
        # The reaper scans only reservations that are still open.
        Index(
            "ix_ai_usage_events_reserved_expiry",
            "reservation_expires_at",
            postgresql_where=text("status = 'reserved'"),
        ),
        CheckConstraint(
            "status IN ('reserved', 'recorded', 'released', 'reversed')",
            name="ck_ai_usage_events_status",
        ),
        CheckConstraint(
            "status <> 'reserved' OR reservation_expires_at IS NOT NULL",
            name="ck_ai_usage_events_reservation_expiry",
        ),
    )

    STATUS_RESERVED = "reserved"
    STATUS_RECORDED = "recorded"
    STATUS_RELEASED = "released"
    STATUS_REVERSED = "reversed"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # SHA-256 over the operation kind and the request payload. Null only for rows written before
    # WP1, which cannot be compared and are returned as they were stored.
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set while the reservation is open. After this instant the reaper may release it.
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
