
"""Tenant-scoped subscription lifecycle model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Subscription(Base):
    """A subscription owned by one organization."""

    __tablename__ = "subscriptions"

    STATUS_TRIALING: ClassVar[str] = "TRIALING"
    STATUS_PENDING: ClassVar[str] = "PENDING"
    STATUS_ACTIVE: ClassVar[str] = "ACTIVE"
    STATUS_PAST_DUE: ClassVar[str] = "PAST_DUE"
    STATUS_PAUSED: ClassVar[str] = "PAUSED"
    STATUS_CANCELLED: ClassVar[str] = "CANCELLED"
    STATUS_EXPIRED: ClassVar[str] = "EXPIRED"

    STATUS_VALUES: ClassVar[tuple[str, ...]] = (
        STATUS_TRIALING,
        STATUS_PENDING,
        STATUS_ACTIVE,
        STATUS_PAST_DUE,
        STATUS_PAUSED,
        STATUS_CANCELLED,
        STATUS_EXPIRED,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('TRIALING', 'PENDING', 'ACTIVE', 'PAST_DUE', "
            "'PAUSED', 'CANCELLED', 'EXPIRED')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "billing_interval IN ('MONTHLY', 'YEARLY')",
            name="ck_subscriptions_billing_interval",
        ),
        CheckConstraint(
            "length(plan_code) > 0",
            name="ck_subscriptions_plan_code_not_empty",
        ),
        Index(
            "ix_subscriptions_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_subscriptions_org_period_end",
            "organization_id",
            "current_period_end",
        ),
        Index(
            "ix_subscriptions_provider_subscription",
            "provider",
            "provider_subscription_id",
            unique=True,
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

    # Replaced by a plan FK in the plan/entitlement story.
    plan_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )

    billing_interval: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="MONTHLY",
        server_default="MONTHLY",
    )

    provider: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    provider_customer_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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
