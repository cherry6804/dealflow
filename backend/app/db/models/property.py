from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.organization import Organization


class Property(Base):
    """Represent a tenant-owned real-estate property record."""

    __tablename__ = "properties"

    TRANSACTION_TYPE_SALE = "SALE"
    TRANSACTION_TYPE_RENT = "RENT"
    TRANSACTION_TYPE_LEASE = "LEASE"

    TRANSACTION_TYPE_VALUES = (
        TRANSACTION_TYPE_SALE,
        TRANSACTION_TYPE_RENT,
        TRANSACTION_TYPE_LEASE,
    )

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

    # ------------------------------------------------------------------
    # DF-154: Availability and status
    # ------------------------------------------------------------------

    STATUS_AVAILABLE = "AVAILABLE"
    STATUS_RESERVED = "RESERVED"
    STATUS_SOLD = "SOLD"
    STATUS_RENTED = "RENTED"
    STATUS_LEASED = "LEASED"
    STATUS_UNAVAILABLE = "UNAVAILABLE"

    STATUS_VALUES = (
        STATUS_AVAILABLE,
        STATUS_RESERVED,
        STATUS_SOLD,
        STATUS_RENTED,
        STATUS_LEASED,
        STATUS_UNAVAILABLE,
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

    # ------------------------------------------------------------------
    # DF-154: Availability and status
    # ------------------------------------------------------------------

    status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # DF-152: Commercial fields
    # ------------------------------------------------------------------

    transaction_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
    )

    rent: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    security_deposit: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    maintenance_charge: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # DF-153: Location fields
    # ------------------------------------------------------------------

    address_line_1: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    address_line_2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    locality: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    state: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    postal_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # DF-153: Property attributes
    # ------------------------------------------------------------------

    property_type: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    bhk: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    built_up_area: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    carpet_area: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    floor_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    total_floors: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Existing Property lifecycle fields
    # ------------------------------------------------------------------

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
        back_populates="properties",
    )