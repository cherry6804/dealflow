"""Append-only consent records per contact, channel and purpose (DFR1-006, ADR-0029 gate 7).

Every grant or revocation is a new row. The current state is the latest row for a contact, channel and
purpose. Rows are never updated or deleted by application code, so the history is the audit trail for
consent. Expiry is evaluated at check time from ``expires_at``.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CONSENT_CHANNELS = ("whatsapp", "email", "sms", "voice")
CONSENT_PURPOSES = ("customer_service", "marketing", "automated_follow_up", "voice_outreach")
CONSENT_STATUSES = ("granted", "revoked")


class ContactConsentRecord(Base):
    __tablename__ = "contact_consent_records"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('whatsapp', 'email', 'sms', 'voice')",
            name="ck_contact_consent_records_channel",
        ),
        CheckConstraint(
            "purpose IN ('customer_service', 'marketing', 'automated_follow_up', 'voice_outreach')",
            name="ck_contact_consent_records_purpose",
        ),
        CheckConstraint("status IN ('granted', 'revoked')", name="ck_contact_consent_records_status"),
        CheckConstraint(
            "status <> 'granted' OR expires_at IS NULL OR expires_at > recorded_at",
            name="ck_contact_consent_records_expiry_after_grant",
        ),
        Index(
            "ix_contact_consent_records_lookup",
            "organization_id",
            "contact_id",
            "channel",
            "purpose",
            "recorded_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    # Scope is the data the consent covers. Only the contact itself is supported today.
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="contact", server_default="contact")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
