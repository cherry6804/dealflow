from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.contact import Contact
    from app.db.models.organization import Organization
    from app.db.models.user import User


class Lead(Base):
    """Represent a tenant-owned DealFlow business opportunity."""

    __tablename__ = "leads"

    __table_args__ = (
        ForeignKeyConstraint(
            ["contact_id", "organization_id"],
            ["contacts.id", "contacts.organization_id"],
            ondelete="CASCADE",
            name="fk_leads_contact_tenant",
        ),
        ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            ondelete="RESTRICT",
            name="fk_leads_owner_membership_tenant",
        ),
    )

    STATUS_NEW = "NEW"
    STATUS_CONTACTED = "CONTACTED"
    STATUS_QUALIFIED = "QUALIFIED"
    STATUS_MATCHING = "MATCHING"
    STATUS_VISIT = "VISIT"
    STATUS_NEGOTIATION = "NEGOTIATION"
    STATUS_WON = "WON"
    STATUS_LOST = "LOST"
    STATUS_ON_HOLD = "ON_HOLD"

    STATUS_VALUES = (
        STATUS_NEW,
        STATUS_CONTACTED,
        STATUS_QUALIFIED,
        STATUS_MATCHING,
        STATUS_VISIT,
        STATUS_NEGOTIATION,
        STATUS_WON,
        STATUS_LOST,
        STATUS_ON_HOLD,
    )

    INTEREST_LOW = "LOW"
    INTEREST_MEDIUM = "MEDIUM"
    INTEREST_HIGH = "HIGH"

    INTEREST_VALUES = (
        INTEREST_LOW,
        INTEREST_MEDIUM,
        INTEREST_HIGH,
    )

    OUTCOME_SUCCESSFUL = "SUCCESSFUL"
    OUTCOME_UNSUCCESSFUL = "UNSUCCESSFUL"

    OUTCOME_VALUES = (
        OUTCOME_SUCCESSFUL,
        OUTCOME_UNSUCCESSFUL,
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

    contact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=STATUS_NEW,
        index=True,
    )

    interest: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
    )

    outcome: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    next_action: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    next_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="leads",
        overlaps="contact,leads",
    )

    contact: Mapped["Contact"] = relationship(
        "Contact",
        back_populates="leads",
        overlaps="organization,leads",
    )

    owner: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[owner_user_id],
    )