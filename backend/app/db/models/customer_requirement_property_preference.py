from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.customer_requirement import CustomerRequirement


class CustomerRequirementPropertyPreference(Base):
    """Represent a property type and BHK preference for a customer requirement."""

    __tablename__ = "customer_requirement_property_preferences"

    PROPERTY_TYPE_APARTMENT = "APARTMENT"
    PROPERTY_TYPE_VILLA = "VILLA"
    PROPERTY_TYPE_INDEPENDENT_HOUSE = "INDEPENDENT_HOUSE"
    PROPERTY_TYPE_PLOT = "PLOT"
    PROPERTY_TYPE_COMMERCIAL = "COMMERCIAL"
    PROPERTY_TYPE_OTHER = "OTHER"

    PROPERTY_TYPE_VALUES = (
        PROPERTY_TYPE_APARTMENT,
        PROPERTY_TYPE_VILLA,
        PROPERTY_TYPE_INDEPENDENT_HOUSE,
        PROPERTY_TYPE_PLOT,
        PROPERTY_TYPE_COMMERCIAL,
        PROPERTY_TYPE_OTHER,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            [
                "customer_requirements.id",
                "customer_requirements.organization_id",
            ],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    customer_requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    property_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    bhk_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    bhk_max: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
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

    customer_requirement: Mapped["CustomerRequirement"] = relationship(
        "CustomerRequirement",
        back_populates="property_preferences",
    )