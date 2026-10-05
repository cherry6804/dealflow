from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.customer_profile import CustomerProfile
    from app.db.models.customer_requirement_location import (
        CustomerRequirementLocation,
    )
    from app.db.models.customer_requirement_possession_parking_preference import (
        CustomerRequirementPossessionParkingPreference,
    )
    from app.db.models.customer_requirement_property_preference import (
        CustomerRequirementPropertyPreference,
    )
    from app.db.models.lead import Lead
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
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_customer_requirements_lead_tenant",
        ),
        ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            ["customer_profiles.id", "customer_profiles.organization_id"],
            name="fk_customer_requirements_customer_profile_tenant",
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

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    customer_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
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
        overlaps="lead,customer_profile",
    )

    lead: Mapped["Lead | None"] = relationship(
        "Lead",
        foreign_keys=[lead_id, organization_id],
        primaryjoin=(
            "and_("
            "CustomerRequirement.lead_id == Lead.id, "
            "CustomerRequirement.organization_id == Lead.organization_id"
            ")"
        ),
        overlaps="organization,customer_profile",
    )

    customer_profile: Mapped["CustomerProfile | None"] = relationship(
        "CustomerProfile",
        foreign_keys=[customer_profile_id, organization_id],
        primaryjoin=(
            "and_("
            "CustomerRequirement.customer_profile_id == CustomerProfile.id, "
            "CustomerRequirement.organization_id == CustomerProfile.organization_id"
            ")"
        ),
        overlaps="organization,lead",
    )

    locations: Mapped[list["CustomerRequirementLocation"]] = relationship(
        "CustomerRequirementLocation",
        back_populates="customer_requirement",
        cascade="all, delete-orphan",
    )

    property_preferences: Mapped[
        list["CustomerRequirementPropertyPreference"]
    ] = relationship(
        "CustomerRequirementPropertyPreference",
        back_populates="customer_requirement",
        cascade="all, delete-orphan",
    )

    possession_parking_preference: Mapped[
        "CustomerRequirementPossessionParkingPreference | None"
    ] = relationship(
        "CustomerRequirementPossessionParkingPreference",
        back_populates="customer_requirement",
        cascade="all, delete-orphan",
        uselist=False,
    )