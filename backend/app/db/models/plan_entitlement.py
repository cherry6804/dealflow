
"""Feature and usage entitlements attached to subscription plans."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.plan import Plan


class PlanEntitlement(Base):
    """A feature flag or limit defined for a subscription plan.

    value_type describes the expected JSON value:
    BOOLEAN, INTEGER, STRING, or JSON.
    """

    __tablename__ = "plan_entitlements"

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "key",
            name="uq_plan_entitlements_plan_key",
        ),
        CheckConstraint(
            "length(key) > 0",
            name="ck_plan_entitlements_key_not_empty",
        ),
        CheckConstraint(
            "value_type IN ('BOOLEAN', 'INTEGER', 'STRING', 'JSON')",
            name="ck_plan_entitlements_value_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    value_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    # JSON supports boolean flags, numeric limits, strings, and structured values.
    value: Mapped[object] = mapped_column(
        JSON,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
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

    plan: Mapped["Plan"] = relationship(
        "Plan",
        back_populates="entitlements",
    )
