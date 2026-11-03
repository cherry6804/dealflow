"""Channel policy: enablement, messaging windows, quiet hours and contact do-not-disturb (DFR1-006).

The gate calls ``evaluate_channel_policy`` for every ``channels.*`` capability, after consent. The first failing
rule decides the reason. An organization with no policy row for a channel has no channel policy, so every channel
execution is denied (fail closed).

Rules, in order:
1. A policy row exists for the channel (``channel_policy_not_configured``).
2. The channel is enabled (``channel_disabled``).
3. The contact is not marked do-not-disturb (``contact_do_not_disturb``).
4. The current local time is inside the messaging window: the weekday is allowed and the time is between start
   and end (``outside_messaging_window``).
5. The current local time is outside quiet hours (``quiet_hours``).

Times are local to the policy's IANA timezone. A window or quiet period may cross midnight. Start and end may
not be equal, because that would be empty or always-on, and the write path refuses both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent
from app.db.models.channel_policy import (
    CHANNEL_POLICY_CHANNELS,
    ChannelPolicy,
    ContactDoNotDisturb,
)
from app.db.models.contact import Contact

REASON_CHANNEL_NOT_CONFIGURED = "channel_policy_not_configured"
REASON_CHANNEL_DISABLED = "channel_disabled"
REASON_CONTACT_DO_NOT_DISTURB = "contact_do_not_disturb"
REASON_OUTSIDE_MESSAGING_WINDOW = "outside_messaging_window"
REASON_QUIET_HOURS = "quiet_hours"

PERMISSION_MANAGE = "governance.channels.manage"
CHANNEL_AUDIT_EVENT_TYPE = "governance"


class ChannelPolicyError(Exception):
    """A channel policy write breaks a rule. The message is safe to show."""


@dataclass(frozen=True)
class ChannelPolicyInput:
    channel: str
    is_enabled: bool
    timezone: str
    messaging_days: int
    messaging_start: time | None
    messaging_end: time | None
    quiet_start: time | None
    quiet_end: time | None


def validate_policy(policy: ChannelPolicyInput) -> None:
    """Refuse configurations that would be ambiguous or would enable a channel without a window."""
    if policy.channel not in CHANNEL_POLICY_CHANNELS:
        raise ChannelPolicyError("Unknown channel.")
    try:
        ZoneInfo(policy.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ChannelPolicyError("The timezone is not a recognised IANA timezone name.") from error
    if not 0 <= policy.messaging_days <= 127:
        raise ChannelPolicyError("Messaging days must be a bit mask from 0 to 127.")
    if (policy.messaging_start is None) != (policy.messaging_end is None):
        raise ChannelPolicyError("A messaging window needs both a start and an end time.")
    if policy.messaging_start is not None and policy.messaging_start == policy.messaging_end:
        raise ChannelPolicyError("The messaging window cannot have equal start and end times.")
    if (policy.quiet_start is None) != (policy.quiet_end is None):
        raise ChannelPolicyError("Quiet hours need both a start and an end time.")
    if policy.quiet_start is not None and policy.quiet_start == policy.quiet_end:
        raise ChannelPolicyError("Quiet hours cannot have equal start and end times.")
    if policy.is_enabled and (
        policy.messaging_days == 0 or policy.messaging_start is None or policy.messaging_end is None
    ):
        raise ChannelPolicyError("An enabled channel needs a messaging window and at least one day.")


def _within(moment: time, start: time, end: time) -> bool:
    """True when ``moment`` is in [start, end). A window with start after end crosses midnight."""
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def evaluate_channel_policy(
    db: Session,
    *,
    organization_id: UUID,
    channel: str,
    contact_id: UUID,
    now: datetime | None = None,
) -> str | None:
    """Return the first denial reason for a channel send to a contact, or None when every rule passes."""
    current = now if now is not None else datetime.now(UTC)
    policy = db.scalar(
        select(ChannelPolicy).where(
            ChannelPolicy.organization_id == organization_id,
            ChannelPolicy.channel == channel,
        )
    )
    if policy is None:
        return REASON_CHANNEL_NOT_CONFIGURED
    if not policy.is_enabled:
        return REASON_CHANNEL_DISABLED
    if policy.messaging_start is None or policy.messaging_end is None:
        return REASON_CHANNEL_NOT_CONFIGURED

    restricted = db.scalar(
        select(ContactDoNotDisturb.id).where(
            ContactDoNotDisturb.organization_id == organization_id,
            ContactDoNotDisturb.contact_id == contact_id,
        )
    )
    if restricted is not None:
        return REASON_CONTACT_DO_NOT_DISTURB

    local = current.astimezone(ZoneInfo(policy.timezone))
    weekday_allowed = bool((policy.messaging_days >> local.weekday()) & 1)
    if not weekday_allowed or not _within(local.time(), policy.messaging_start, policy.messaging_end):
        return REASON_OUTSIDE_MESSAGING_WINDOW
    if (
        policy.quiet_start is not None
        and policy.quiet_end is not None
        and _within(local.time(), policy.quiet_start, policy.quiet_end)
    ):
        return REASON_QUIET_HOURS
    return None


def _audit(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    action: str,
    resource_id: str,
    metadata: dict[str, object],
) -> None:
    db.add(
        AuditEvent(
            occurred_at=datetime.now(UTC),
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=CHANNEL_AUDIT_EVENT_TYPE,
            action=action,
            decision="allowed",
            permission_key=PERMISSION_MANAGE,
            resource_type="channel_policy",
            resource_id=resource_id,
            event_metadata=json.dumps(metadata, sort_keys=True, default=str),
        )
    )
    db.flush()


def set_channel_policy(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    policy: ChannelPolicyInput,
    now: datetime | None = None,
) -> ChannelPolicy:
    """Create or replace the policy for one channel. Every change is audited with the new values."""
    validate_policy(policy)
    current = now if now is not None else datetime.now(UTC)
    row = db.scalar(
        select(ChannelPolicy).where(
            ChannelPolicy.organization_id == organization_id,
            ChannelPolicy.channel == policy.channel,
        )
    )
    if row is None:
        row = ChannelPolicy(organization_id=organization_id, channel=policy.channel)
        db.add(row)
    row.is_enabled = policy.is_enabled
    row.timezone = policy.timezone
    row.messaging_days = policy.messaging_days
    row.messaging_start = policy.messaging_start
    row.messaging_end = policy.messaging_end
    row.quiet_start = policy.quiet_start
    row.quiet_end = policy.quiet_end
    row.updated_by_user_id = actor_user_id
    row.updated_at = current
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="governance.channel_policy.updated",
        resource_id=policy.channel,
        metadata={
            "channel": policy.channel,
            "is_enabled": policy.is_enabled,
            "timezone": policy.timezone,
            "messaging_days": policy.messaging_days,
            "messaging_start": policy.messaging_start.isoformat() if policy.messaging_start else None,
            "messaging_end": policy.messaging_end.isoformat() if policy.messaging_end else None,
            "quiet_start": policy.quiet_start.isoformat() if policy.quiet_start else None,
            "quiet_end": policy.quiet_end.isoformat() if policy.quiet_end else None,
        },
    )
    return row


def set_contact_do_not_disturb(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    contact_id: UUID,
    enabled: bool,
) -> bool:
    """Mark or unmark a contact as do-not-disturb. The contact must belong to the organization."""
    contact = db.scalar(
        select(Contact.id).where(Contact.id == contact_id, Contact.organization_id == organization_id)
    )
    if contact is None:
        raise ChannelPolicyError("Contact not found.")
    row = db.scalar(
        select(ContactDoNotDisturb).where(
            ContactDoNotDisturb.organization_id == organization_id,
            ContactDoNotDisturb.contact_id == contact_id,
        )
    )
    if enabled and row is None:
        db.add(ContactDoNotDisturb(organization_id=organization_id, contact_id=contact_id, set_by_user_id=actor_user_id))
    elif not enabled and row is not None:
        db.delete(row)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="governance.contact_do_not_disturb.updated",
        resource_id=str(contact_id),
        metadata={"contact_id": str(contact_id), "enabled": enabled},
    )
    return enabled
