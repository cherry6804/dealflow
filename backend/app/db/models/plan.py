
"""Reusable subscription plan catalog."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.plan_entitlement import PlanEntitlement
    from app.db.models.subscription import Subscription


class Plan(Base):
    """A reusable plan offered to DealFlow organizations."""

    __tablename__ = "plans"

    __table_args__ = (
        CheckConstraint(
            "length(code) > 0",
            name="ck_plans_code_not_empty",
        ),
        CheckConstraint(
            "monthly_price_paise IS NULL OR monthly_price_paise >= 0",
            name="ck_plans_price_nonnegative",
        ),
        CheckConstraint(
            "included_seats IS NULL OR included_seats > 0",
            name="ck_plans_included_seats_positive",
        ),
        CheckConstraint(
            "currency = 'INR'",
            name="ck_plans_currency_inr",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Store money as integer paise to avoid floating-point rounding.
    # NULL is allowed for custom-priced Enterprise plans.
    monthly_price_paise: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )

    # NULL means the plan has no fixed included-seat limit.
    included_seats: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    is_custom_pricing: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
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

    entitlements: Mapped[list["PlanEntitlement"]] = relationship(
        "PlanEntitlement",
        back_populates="plan",
        cascade="all, delete-orphan",
    )

    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription",
        back_populates="plan",
    )
