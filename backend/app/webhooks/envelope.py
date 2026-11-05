"""Normalised event envelope for verified inbound webhooks (DFR1-012).

Only a verified body reaches this module. The body is parsed strictly: it must be one JSON object, with no duplicate keys, and
the envelope fields must have the expected types and limits. Anything else is malformed and is recorded without its body.

The envelope is the same for every provider: provider, provider event ID, event type, occurred-at time, received-at time, correlation
ID and the redacted payload. Provider-specific fields are mapped by provider adapters, not here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.webhooks.redaction import redact_payload

MAX_BODY_BYTES = 256 * 1024
MAX_JSON_DEPTH = 12
MAX_EVENT_ID_LENGTH = 200
MAX_EVENT_TYPE_LENGTH = 120
ENVELOPE_VERSION = 1

_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,199}$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")


class MalformedWebhook(ValueError):
    """The body is not a valid envelope. ``reason`` is a stable code that is safe to store and show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class NormalizedEvent:
    provider_event_id: str
    event_type: str
    occurred_at: datetime | None
    payload: dict[str, Any]

    def envelope(
        self, *, provider_key: str, received_at: datetime, correlation_id: str
    ) -> dict[str, Any]:
        return {
            "envelope_version": ENVELOPE_VERSION,
            "provider": provider_key,
            "provider_event_id": self.provider_event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "received_at": received_at.astimezone(UTC).isoformat(),
            "correlation_id": correlation_id,
            "payload": self.payload,
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedWebhook("duplicate_key")
        result[key] = value
    return result


def _depth(value: object, level: int = 0) -> int:
    if isinstance(value, dict):
        return max([level + 1] + [_depth(item, level + 1) for item in value.values()])
    if isinstance(value, list):
        return max([level + 1] + [_depth(item, level + 1) for item in value])
    return level


def _parse_instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise MalformedWebhook("malformed_occurred_at")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise MalformedWebhook("malformed_occurred_at") from None
    if parsed.tzinfo is None:
        raise MalformedWebhook("malformed_occurred_at")
    return parsed.astimezone(UTC)


def normalize(body: bytes) -> NormalizedEvent:
    """Parse and check a verified body. Raises ``MalformedWebhook`` with a stable reason."""
    if not body or len(body) > MAX_BODY_BYTES:
        raise MalformedWebhook("body_size")
    try:
        text = body.decode("utf-8")
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except MalformedWebhook:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise MalformedWebhook("invalid_json") from None
    if not isinstance(data, dict):
        raise MalformedWebhook("not_an_object")
    if _depth(data) > MAX_JSON_DEPTH:
        raise MalformedWebhook("too_deep")

    event_id = data.get("id")
    if (
        not isinstance(event_id, str)
        or len(event_id) > MAX_EVENT_ID_LENGTH
        or not _EVENT_ID.match(event_id)
    ):
        raise MalformedWebhook("malformed_event_id")
    event_type = data.get("type")
    if (
        not isinstance(event_type, str)
        or len(event_type) > MAX_EVENT_TYPE_LENGTH
        or not _EVENT_TYPE.match(event_type)
    ):
        raise MalformedWebhook("malformed_event_type")
    occurred_at = (
        _parse_instant(data["occurred_at"])
        if data.get("occurred_at") is not None
        else None
    )
    payload = data.get("data", {})
    if not isinstance(payload, dict):
        raise MalformedWebhook("malformed_data")

    return NormalizedEvent(
        provider_event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=redact_payload(payload),
    )
