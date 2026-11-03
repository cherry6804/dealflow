"""Per-organization channel policy and per-contact do-not-disturb (DFR1-006, ADR-0029 gate 7).

A channel policy says whether one channel may be used at all, in which timezone, inside which messaging window,
and outside which quiet hours. An organization without a row for a channel has no policy, and the gate denies
(fail closed). Do-not-disturb is a contact-level restriction: a row here blocks every channel for that contact.
"""

import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CHANNEL_POLICY_CHANNELS = ("whatsapp", "email", "sms", "voice")


class ChannelPolicy(Base):
    __tablename__ = "channel_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", "channel", name="uq_channel_policies_org_channel"),
        CheckConstraint(
            "channel IN ('whatsapp', 'email', 'sms', 'voice')",
            name="ck_channel_policies_channel",
        ),
        CheckConstraint("messaging_days BETWEEN 0 AND 127", name="ck_channel_policies_days"),
        CheckConstraint(
            "(messaging_start IS NULL) = (messaging_end IS NULL)",
            name="ck_channel_policies_window_pair",
        ),
        CheckConstraint(
            "(quiet_start IS NULL) = (quiet_end IS NULL)",
            name="ck_channel_policies_quiet_pair",
        ),
        Index("ix_channel_policies_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # IANA timezone name, for example "Asia/Kolkata". Windows and quiet hours are local to it.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # Bit 0 is Monday through bit 6 is Sunday. Zero is never valid for an enabled channel.
    messaging_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    messaging_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    messaging_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContactDoNotDisturb(Base):
    __tablename__ = "contact_do_not_disturb"
    __table_args__ = (
        UniqueConstraint("organization_id", "contact_id", name="uq_contact_dnd_org_contact"),
        Index("ix_contact_dnd_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    set_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
