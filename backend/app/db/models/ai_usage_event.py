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
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_ai_usage_events_org_idempotency",
        ),
        Index("ix_ai_usage_events_org_occurred", "organization_id", "occurred_at"),
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
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
