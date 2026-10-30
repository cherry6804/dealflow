
"""Database model for tenant-scoped referral records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Referral(Base):
    """Record referrals associated with customers, contacts, and deals."""

    __tablename__ = "referrals"

    STATUS_NEW = "NEW"
    STATUS_CONTACTED = "CONTACTED"
    STATUS_CONVERTED = "CONVERTED"
    STATUS_NOT_CONVERTED = "NOT_CONVERTED"

    STATUS_VALUES = (
        STATUS_NEW,
        STATUS_CONTACTED,
        STATUS_CONVERTED,
        STATUS_NOT_CONVERTED,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_profile_id", "organization_id"],
            ["customer_profiles.id", "customer_profiles.organization_id"],
            name="fk_referrals_customer_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["referrer_contact_id", "organization_id"],
            ["contacts.id", "contacts.organization_id"],
            name="fk_referrals_referrer_contact_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_referrals_deal_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('NEW', 'CONTACTED', 'CONVERTED', 'NOT_CONVERTED')",
            name="ck_referrals_status",
        ),
        CheckConstraint(
            """
            customer_profile_id IS NOT NULL
            OR referrer_contact_id IS NOT NULL
            OR deal_id IS NOT NULL
            """,
            name="ck_referrals_has_association",
        ),
        Index(
            "ix_referrals_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_referrals_org_customer",
            "organization_id",
            "customer_profile_id",
        ),
        Index(
            "ix_referrals_org_referrer",
            "organization_id",
            "referrer_contact_id",
        ),
        Index(
            "ix_referrals_org_deal",
            "organization_id",
            "deal_id",
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

    customer_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    referrer_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    referral_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    referral_phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    referral_email: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=STATUS_NEW,
        server_default=STATUS_NEW,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
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
