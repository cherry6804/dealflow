from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.customer_requirement import CustomerRequirement


class CustomerRequirementLocation(Base):
    """Represent a preferred location for a customer requirement."""

    __tablename__ = "customer_requirement_locations"

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

    city: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    locality: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
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
        back_populates="locations",
    )