
"""Database model for commission terms associated with a deal."""

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


class DealCommission(Base):
    """Track proposed and agreed commission terms for a tenant-owned deal."""

    __tablename__ = "deal_commissions"

    TYPE_FIXED = "FIXED"
    TYPE_PERCENTAGE = "PERCENTAGE"
    TYPE_VALUES = (TYPE_FIXED, TYPE_PERCENTAGE)

    STATUS_PROPOSED = "PROPOSED"
    STATUS_AGREED = "AGREED"
    STATUS_PAID = "PAID"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_VALUES = (
        STATUS_PROPOSED,
        STATUS_AGREED,
        STATUS_PAID,
        STATUS_CANCELLED,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_deal_commissions_deal_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "commission_type IN ('FIXED', 'PERCENTAGE')",
            name="ck_deal_commissions_type",
        ),
        CheckConstraint(
            "status IN ('PROPOSED', 'AGREED', 'PAID', 'CANCELLED')",
            name="ck_deal_commissions_status",
        ),
        CheckConstraint(
            """
            (
                commission_type = 'FIXED'
                AND fixed_amount IS NOT NULL
                AND fixed_amount > 0
                AND rate_percent IS NULL
            )
            OR
            (
                commission_type = 'PERCENTAGE'
                AND rate_percent IS NOT NULL
                AND rate_percent > 0
                AND rate_percent <= 100
                AND fixed_amount IS NULL
            )
            """,
            name="ck_deal_commissions_amount_or_rate",
        ),
        CheckConstraint(
            "status != 'PAID' OR paid_at IS NOT NULL",
            name="ck_deal_commissions_paid_timestamp",
        ),
        Index(
            "ix_deal_commissions_org_deal",
            "organization_id",
            "deal_id",
        ),
        Index(
            "ix_deal_commissions_org_status",
            "organization_id",
            "status",
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

    commission_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    fixed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    rate_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4),
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PROPOSED,
        server_default=STATUS_PROPOSED,
        index=True,
    )

    terms: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    agreed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
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
