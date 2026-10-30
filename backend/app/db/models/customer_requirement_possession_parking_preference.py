from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.customer_requirement import CustomerRequirement


class CustomerRequirementPossessionParkingPreference(Base):
    """Represent possession and parking preferences for a customer requirement."""

    __tablename__ = "customer_requirement_possession_parking_preferences"

    POSSESSION_READY_TO_MOVE = "READY_TO_MOVE"
    POSSESSION_WITHIN_3_MONTHS = "WITHIN_3_MONTHS"
    POSSESSION_WITHIN_6_MONTHS = "WITHIN_6_MONTHS"
    POSSESSION_WITHIN_12_MONTHS = "WITHIN_12_MONTHS"
    POSSESSION_AFTER_12_MONTHS = "AFTER_12_MONTHS"
    POSSESSION_ANY = "ANY"

    POSSESSION_PREFERENCE_VALUES = (
        POSSESSION_READY_TO_MOVE,
        POSSESSION_WITHIN_3_MONTHS,
        POSSESSION_WITHIN_6_MONTHS,
        POSSESSION_WITHIN_12_MONTHS,
        POSSESSION_AFTER_12_MONTHS,
        POSSESSION_ANY,
    )

    PARKING_REQUIRED = "REQUIRED"
    PARKING_PREFERRED = "PREFERRED"
    PARKING_NOT_REQUIRED = "NOT_REQUIRED"
    PARKING_ANY = "ANY"

    PARKING_PREFERENCE_VALUES = (
        PARKING_REQUIRED,
        PARKING_PREFERRED,
        PARKING_NOT_REQUIRED,
        PARKING_ANY,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            [
                "customer_requirements.id",
                "customer_requirements.organization_id",
            ],
            name="fk_req_possession_parking_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "customer_requirement_id",
            "organization_id",
            name="uq_req_possession_parking_req",
        ),
        Index(
            "ix_req_possession_parking_org",
            "organization_id",
        ),
        Index(
            "ix_req_possession_parking_req",
            "customer_requirement_id",
        ),
        Index(
            "ix_req_possession_parking_active",
            "is_active",
        ),
        Index(
            "ix_req_possession_parking_possession",
            "possession_preference",
        ),
        Index(
            "ix_req_possession_parking_parking",
            "parking_preference",
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
    )

    customer_requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    possession_preference: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    parking_preference: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    parking_spaces_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
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
        back_populates="possession_parking_preference",
    )