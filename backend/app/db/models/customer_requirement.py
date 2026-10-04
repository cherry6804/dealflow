from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.customer_requirement_location import (
        CustomerRequirementLocation,
    )
    from app.db.models.organization import Organization


class CustomerRequirement(Base):
    """Represent a tenant-owned customer requirement in DealFlow."""

    __tablename__ = "customer_requirements"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_customer_requirements_id_organization_id",
        ),
    )

    STATUS_ACTIVE = "ACTIVE"
    STATUS_INACTIVE = "INACTIVE"

    STATUS_VALUES = (
        STATUS_ACTIVE,
        STATUS_INACTIVE,
    )

    DEFAULT_BUDGET_CURRENCY = "INR"

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

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=STATUS_ACTIVE,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    budget_min: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    budget_max: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    budget_currency: Mapped[str | None] = mapped_column(
        String(3),
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

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="customer_requirements",
    )

    locations: Mapped[list["CustomerRequirementLocation"]] = relationship(
        "CustomerRequirementLocation",
        back_populates="customer_requirement",
        cascade="all, delete-orphan",
    )