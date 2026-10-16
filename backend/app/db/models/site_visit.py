
"""Tenant-owned real estate site visits."""

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
    from app.db.models.organization import Organization


class SiteVisit(Base):
    """Represent a scheduled or completed property visit."""

    __tablename__ = "site_visits"

    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_NO_SHOW = "NO_SHOW"

    STATUS_VALUES = (
        STATUS_SCHEDULED,
        STATUS_COMPLETED,
        STATUS_CANCELLED,
        STATUS_NO_SHOW,
    )

    OUTCOME_INTERESTED = "INTERESTED"
    OUTCOME_NOT_INTERESTED = "NOT_INTERESTED"
    OUTCOME_NEGOTIATION = "NEGOTIATION"
    OUTCOME_FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    OUTCOME_OTHER = "OTHER"

    OUTCOME_VALUES = (
        OUTCOME_INTERESTED,
        OUTCOME_NOT_INTERESTED,
        OUTCOME_NEGOTIATION,
        OUTCOME_FOLLOW_UP_REQUIRED,
        OUTCOME_OTHER,
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_site_visits_id_organization",
        ),
        ForeignKeyConstraint(
            ["property_id", "organization_id"],
            ["properties.id", "properties.organization_id"],
            name="fk_site_visits_property_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_site_visits_lead_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            [
                "customer_profiles.id",
                "customer_profiles.organization_id",
            ],
            name="fk_site_visits_customer_profile_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_site_visits_owner_membership_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('SCHEDULED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name="ck_site_visits_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('INTERESTED', 'NOT_INTERESTED', 'NEGOTIATION', "
            "'FOLLOW_UP_REQUIRED', 'OTHER')",
            name="ck_site_visits_outcome",
        ),
        CheckConstraint(
            "ends_at IS NULL OR ends_at > scheduled_at",
            name="ck_site_visits_time_range",
        ),
        CheckConstraint(
            "lead_id IS NOT NULL OR customer_profile_id IS NOT NULL",
            name="ck_site_visits_customer_reference",
        ),
        Index(
            "ix_site_visits_org_scheduled_at",
            "organization_id",
            "scheduled_at",
        ),
        Index(
            "ix_site_visits_org_property_scheduled",
            "organization_id",
            "property_id",
            "scheduled_at",
        ),
        Index(
            "ix_site_visits_org_owner_status_scheduled",
            "organization_id",
            "owner_user_id",
            "status",
            "scheduled_at",
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
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    customer_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_SCHEDULED,
        server_default=STATUS_SCHEDULED,
    )

    outcome: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
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

    organization: Mapped[Organization] = relationship(
        "Organization",
    )
