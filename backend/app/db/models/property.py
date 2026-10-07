from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid, func
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