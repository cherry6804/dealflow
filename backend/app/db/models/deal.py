
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.user import User

class Deal(Base):
    """Represent a tenant-owned real-estate transaction."""

    __tablename__ = "deals"

    STAGE_NEW = "NEW"
    STAGE_QUALIFICATION = "QUALIFICATION"
    STAGE_NEGOTIATION = "NEGOTIATION"
    STAGE_BOOKING = "BOOKING"
    STAGE_CLOSED_WON = "CLOSED_WON"
    STAGE_CLOSED_LOST = "CLOSED_LOST"

    STAGE_VALUES = (
        STAGE_NEW,
        STAGE_QUALIFICATION,
        STAGE_NEGOTIATION,
        STAGE_BOOKING,
        STAGE_CLOSED_WON,
        STAGE_CLOSED_LOST,
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_deals_id_organization_id",
        ),
        ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            [
                "customer_profiles.id",
                "customer_profiles.organization_id",
            ],
            name="fk_deals_customer_profile_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["property_id", "organization_id"],
            ["properties.id", "properties.organization_id"],
            name="fk_deals_property_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_deals_lead_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_deals_owner_membership_tenant",
            ondelete="RESTRICT",
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

    customer_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    # A deal can optionally originate from an existing lead.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    stage: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=STAGE_NEW,
        server_default=STAGE_NEW,
        index=True,
    )

    expected_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
        server_default="INR",
    )

    notes: Mapped[str | None] = mapped_column(
        String(2000),
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

    owner: Mapped["User"] = relationship(
        "User",
        primaryjoin="User.id == foreign(Deal.owner_user_id)",
        foreign_keys="[Deal.owner_user_id]",
        viewonly=True,
    )

    @property
    def owner_name(self) -> str | None:
        """Return the display name of the assigned deal owner."""
        return self.owner.display_name if self.owner else None
