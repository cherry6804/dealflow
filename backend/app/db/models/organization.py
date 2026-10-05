import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.contact import Contact
    from app.db.models.customer_profile import CustomerProfile
    from app.db.models.customer_requirement import CustomerRequirement
    from app.db.models.lead import Lead
    from app.db.models.membership import Membership


class Organization(Base):
    """Represent a DealFlow customer organization and tenant."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
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

    memberships: Mapped[list["Membership"]] = relationship(
        "Membership",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    contacts: Mapped[list["Contact"]] = relationship(
        "Contact",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    customer_profiles: Mapped[list["CustomerProfile"]] = relationship(
        "CustomerProfile",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    customer_requirements: Mapped[list["CustomerRequirement"]] = relationship(
        "CustomerRequirement",
        back_populates="organization",
        cascade="all, delete-orphan",
        overlaps="lead,customer_profile",
    )

    leads: Mapped[list["Lead"]] = relationship(
        "Lead",
        back_populates="organization",
        cascade="all, delete-orphan",
        overlaps="contact,leads",
    )