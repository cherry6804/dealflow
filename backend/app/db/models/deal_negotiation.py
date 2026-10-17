
"""Negotiation state and change history for real-estate deals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.deal import Deal
    from app.db.models.user import User


class DealNegotiation(Base):
    """Store the current negotiation state for one tenant-owned deal."""

    __tablename__ = "deal_negotiations"

    STATE_IN_PROGRESS = "IN_PROGRESS"
    STATE_WAITING_ON_CUSTOMER = "WAITING_ON_CUSTOMER"
    STATE_WAITING_ON_SELLER = "WAITING_ON_SELLER"
    STATE_TERMS_AGREED = "TERMS_AGREED"
    STATE_STALLED = "STALLED"
    STATE_COMPLETED = "COMPLETED"
    STATE_CANCELLED = "CANCELLED"

    STATE_VALUES = (
        STATE_IN_PROGRESS,
        STATE_WAITING_ON_CUSTOMER,
        STATE_WAITING_ON_SELLER,
        STATE_TERMS_AGREED,
        STATE_STALLED,
        STATE_COMPLETED,
        STATE_CANCELLED,
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_deal_negotiations_id_organization_id",
        ),
        UniqueConstraint(
            "deal_id",
            name="uq_deal_negotiations_deal_id",
        ),
        ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_deal_negotiations_deal_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["updated_by_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_deal_negotiations_updated_by_membership_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ("
            "'IN_PROGRESS', 'WAITING_ON_CUSTOMER', "
            "'WAITING_ON_SELLER', 'TERMS_AGREED', 'STALLED', "
            "'COMPLETED', 'CANCELLED')",
            name="ck_deal_negotiations_state",
        ),
        Index(
            "ix_deal_negotiations_org_state",
            "organization_id",
            "state",
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

    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=STATE_IN_PROGRESS,
        server_default=STATE_IN_PROGRESS,
    )

    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
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

    deal: Mapped["Deal"] = relationship(
        "Deal",
        primaryjoin=(
            "Deal.id == foreign(DealNegotiation.deal_id)"
        ),
        viewonly=True,
    )

    updated_by: Mapped["User"] = relationship(
        "User",
        primaryjoin=(
            "User.id == foreign(DealNegotiation.updated_by_user_id)"
        ),
        viewonly=True,
    )


class DealNegotiationHistory(Base):
    """Append-only history of negotiation state changes."""

    __tablename__ = "deal_negotiation_history"

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_deal_negotiation_history_id_organization_id",
        ),
        ForeignKeyConstraint(
            ["negotiation_id", "organization_id"],
            [
                "deal_negotiations.id",
                "deal_negotiations.organization_id",
            ],
            name="fk_deal_negotiation_history_negotiation_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["actor_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_deal_negotiation_history_actor_membership_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "to_state IN ("
            "'IN_PROGRESS', 'WAITING_ON_CUSTOMER', "
            "'WAITING_ON_SELLER', 'TERMS_AGREED', 'STALLED', "
            "'COMPLETED', 'CANCELLED')",
            name="ck_deal_negotiation_history_to_state",
        ),
        CheckConstraint(
            "from_state IS NULL OR from_state IN ("
            "'IN_PROGRESS', 'WAITING_ON_CUSTOMER', "
            "'WAITING_ON_SELLER', 'TERMS_AGREED', 'STALLED', "
            "'COMPLETED', 'CANCELLED')",
            name="ck_deal_negotiation_history_from_state",
        ),
        Index(
            "ix_deal_negotiation_history_org_negotiation_created",
            "organization_id",
            "negotiation_id",
            "created_at",
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

    negotiation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    from_state: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    to_state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    actor: Mapped["User"] = relationship(
        "User",
        primaryjoin=(
            "User.id == foreign(DealNegotiationHistory.actor_user_id)"
        ),
        viewonly=True,
    )
