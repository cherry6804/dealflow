"""Contact consent: record, revoke, expire and check (DFR1-006, ADR-0029 gate 7).

Consent is organization-scoped and per contact, channel and purpose. Each change appends a row, so the
history is complete and nothing is overwritten. The current state is the latest row. A grant with an expiry
time is effective only until that time, which is evaluated at check time.

Policy version: ``CONSENT_POLICY_VERSION`` is recorded on every row. Changing what a purpose means requires a
new version and an approved change to the catalogue. Until then, version 1 is the only version.

Not implemented here, and not claimed: quiet hours, messaging windows, template rules and do-not-disturb
lists (the rest of ADR-0029 gate 7). Consent is checked; those rules are not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.contact_consent import (
    CONSENT_CHANNELS,
    CONSENT_PURPOSES,
    CONSENT_STATUSES,
    ContactConsentRecord,
)

CONSENT_POLICY_VERSION = 1
CONSENT_AUDIT_EVENT_TYPE = "governance"
CONSENT_AUDIT_ACTION = "consent.recorded"
CONSENT_SOURCE_PATTERN = r"^[a-z][a-z_]{1,39}$"

EFFECTIVE_GRANTED = "granted"
EFFECTIVE_REVOKED = "revoked"
EFFECTIVE_EXPIRED = "expired"
EFFECTIVE_NONE = "none"


class ConsentError(Exception):
    """Base class for consent rule violations."""


class ContactNotFoundError(ConsentError):
    """The contact does not exist in the organization."""


class InvalidConsentError(ConsentError):
    """The consent request breaks a rule (channel, purpose, status, expiry or source)."""


@dataclass(frozen=True)
class ConsentSubject:
    """The contact and the consent a capability needs before it may act on that contact."""

    contact_id: UUID
    channel: str
    purpose: str


@dataclass(frozen=True)
class ConsentState:
    """Effective consent at one moment, with the record that decides it (None when no record exists)."""

    effective: str
    record: ContactConsentRecord | None


def _validate(channel: str, purpose: str, status: str, source: str, expires_at: datetime | None, now: datetime) -> None:
    if channel not in CONSENT_CHANNELS:
        raise InvalidConsentError("Unknown consent channel.")
    if purpose not in CONSENT_PURPOSES:
        raise InvalidConsentError("Unknown consent purpose.")
    if status not in CONSENT_STATUSES:
        raise InvalidConsentError("Consent status must be granted or revoked.")
    if not source or len(source) > 40 or not source.replace("_", "").isalpha() or source != source.lower():
        raise InvalidConsentError("Consent source must be a short lowercase code.")
    if status == "granted" and expires_at is not None and expires_at <= now:
        raise InvalidConsentError("A consent grant cannot expire in the past.")
    if status == "revoked" and expires_at is not None:
        raise InvalidConsentError("A revocation does not carry an expiry.")


def record_consent(
    db: Session,
    *,
    organization_id: UUID,
    contact_id: UUID,
    channel: str,
    purpose: str,
    status: str,
    source: str,
    actor_user_id: UUID,
    evidence_note: str | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> ContactConsentRecord:
    """Append a grant or revocation for one contact, channel and purpose, and audit it."""
    current_time = now if now is not None else datetime.now(UTC)
    _validate(channel, purpose, status, source, expires_at, current_time)
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.organization_id == organization_id)
    )
    if contact is None:
        # The same answer for a missing and another organization's contact, so no tenant is revealed.
        raise ContactNotFoundError("Contact not found.")

    previous = current_consent(
        db,
        organization_id=organization_id,
        contact_id=contact_id,
        channel=channel,
        purpose=purpose,
        now=current_time,
    )
    record = ContactConsentRecord(
        organization_id=organization_id,
        contact_id=contact_id,
        channel=channel,
        purpose=purpose,
        scope="contact",
        status=status,
        policy_version=CONSENT_POLICY_VERSION,
        source=source,
        evidence_note=evidence_note.strip()[:500] if evidence_note and evidence_note.strip() else None,
        expires_at=expires_at,
        recorded_by_user_id=actor_user_id,
        recorded_at=current_time,
    )
    db.add(record)
    db.flush()
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=CONSENT_AUDIT_EVENT_TYPE,
            action=CONSENT_AUDIT_ACTION,
            decision="allowed",
            permission_key="governance.consent.manage",
            resource_type="contact_consent",
            resource_id=str(record.id),
            occurred_at=current_time,
            event_metadata=json.dumps(
                {
                    "channel": channel,
                    "purpose": purpose,
                    "status": status,
                    "policy_version": CONSENT_POLICY_VERSION,
                    "source": source,
                    "previous_effective": previous.effective,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()
    return record


def current_consent(
    db: Session,
    *,
    organization_id: UUID,
    contact_id: UUID,
    channel: str,
    purpose: str,
    now: datetime | None = None,
) -> ConsentState:
    """The effective consent now: the latest record, adjusted for expiry."""
    current_time = now if now is not None else datetime.now(UTC)
    record = db.scalar(
        select(ContactConsentRecord)
        .where(
            ContactConsentRecord.organization_id == organization_id,
            ContactConsentRecord.contact_id == contact_id,
            ContactConsentRecord.channel == channel,
            ContactConsentRecord.purpose == purpose,
        )
        .order_by(ContactConsentRecord.recorded_at.desc(), ContactConsentRecord.id.desc())
        .limit(1)
    )
    if record is None:
        return ConsentState(EFFECTIVE_NONE, None)
    if record.status == "revoked":
        return ConsentState(EFFECTIVE_REVOKED, record)
    if record.expires_at is not None and record.expires_at <= current_time:
        return ConsentState(EFFECTIVE_EXPIRED, record)
    return ConsentState(EFFECTIVE_GRANTED, record)


def consent_history(
    db: Session,
    *,
    organization_id: UUID,
    contact_id: UUID,
) -> list[ContactConsentRecord]:
    """Every consent change for one contact in this organization, oldest first."""
    return list(
        db.scalars(
            select(ContactConsentRecord)
            .where(
                ContactConsentRecord.organization_id == organization_id,
                ContactConsentRecord.contact_id == contact_id,
            )
            .order_by(ContactConsentRecord.recorded_at, ContactConsentRecord.id)
        ).all()
    )
