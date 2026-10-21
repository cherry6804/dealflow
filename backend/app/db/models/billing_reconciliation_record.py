
"""Persistent audit record for billing webhook reconciliation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Uuid,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BillingReconciliationRecord(Base):
    """Record the result of reconciling a verified billing webhook."""

    __tablename__ = "billing_reconciliation_records"

    STATUS_MATCHED: ClassVar[str] = "MATCHED"
    STATUS_MISMATCHED: ClassVar[str] = "MISMATCHED"
    STATUS_FAILED: ClassVar[str] = "FAILED"

    STATUS_VALUES: ClassVar[tuple[str, ...]] = (
        STATUS_MATCHED,
        STATUS_MISMATCHED,
        STATUS_FAILED,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('MATCHED', 'MISMATCHED', 'FAILED')",
            name="ck_billing_reconciliation_records_status",
        ),
        Index(
            "ix_billing_reconciliation_records_event_created",
            "webhook_event_id",
            "created_at",
        ),
        Index(
            "ix_billing_reconciliation_records_organization_id",
            "organization_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    webhook_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("billing_webhook_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    reconciled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
