
"""Database model for deal payment milestones."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentMilestone(Base):
    """Track an expected payment associated with a tenant-owned deal."""

    __tablename__ = "payment_milestones"

    STATUS_PENDING = "PENDING"
    STATUS_PAID = "PAID"
    STATUS_CANCELLED = "CANCELLED"

    __table_args__ = (
        ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_payment_milestones_deal_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_payment_milestones_amount_positive",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PAID', 'CANCELLED')",
            name="ck_payment_milestones_status",
        ),
        CheckConstraint(
            "status != 'PAID' OR paid_at IS NOT NULL",
            name="ck_payment_milestones_paid_timestamp",
        ),
        Index(
            "ix_payment_milestones_org_deal_due",
            "organization_id",
            "deal_id",
            "due_at",
        ),
        Index(
            "ix_payment_milestones_org_status_due",
            "organization_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    paid_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

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
