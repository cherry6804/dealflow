"""Verification of SIBVO's signed organization-level entitlement snapshot (WS5, ADR-0027).

SIBVO signs each snapshot with HMAC-SHA256 over the canonical JSON of the snapshot object. This
module checks the signature and the binding, then applies the same entitlement rules as a session
snapshot (``evaluate_feature_access``). A snapshot that fails any check is never used, and the
stored snapshot is not replaced by it.

Canonical bytes must match SIBVO's ``canonical_bytes``: keys sorted, separators without spaces,
ASCII output. Changing that rule breaks every signature, so both repositories pin it in tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.governance.entitlement import EntitlementVerdict, evaluate_feature_access

SNAPSHOT_VERSION = 1
SIGNATURE_ALGORITHM = "HMAC-SHA256"
# Clock skew tolerated when a snapshot's issue time is slightly ahead of this process.
ISSUED_AT_SKEW = timedelta(seconds=5)
MAX_SNAPSHOT_LIFETIME = timedelta(seconds=30)
MIN_SIGNING_KEY_LENGTH = 32


class SnapshotRejected(Exception):
    """A SIBVO response is not a usable snapshot. ``reason`` is a stable code, never data."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SibvoDenied(Exception):
    """SIBVO answered ``active: false``. The organization has no current access."""


@dataclass(frozen=True)
class VerifiedSnapshot:
    snapshot_id: str
    organization_id: UUID
    product_key: str
    subscription_status: str
    issued_at: datetime
    expires_at: datetime
    snapshot: dict[str, Any]
    signature: str
    key_id: str


def canonical_bytes(snapshot: dict[str, Any]) -> bytes:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return encoded.encode("utf-8")


def compute_signature(snapshot: dict[str, Any], signing_key: str) -> str:
    digest = hmac.new(signing_key.encode("utf-8"), canonical_bytes(snapshot), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _parse_instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise SnapshotRejected("malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SnapshotRejected("malformed") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotRejected("malformed")
    return parsed.astimezone(UTC)


def verify_snapshot(
    body: object,
    *,
    signing_key: str | None,
    key_id: str,
    organization_id: UUID,
    product_key: str,
    now: datetime,
) -> VerifiedSnapshot:
    """Return the verified snapshot, or raise ``SnapshotRejected`` / ``SibvoDenied``."""
    if not isinstance(body, dict):
        raise SnapshotRejected("malformed")
    if body.get("active") is False:
        raise SibvoDenied()
    if body.get("active") is not True:
        raise SnapshotRejected("malformed")

    if signing_key is None or len(signing_key.strip()) < MIN_SIGNING_KEY_LENGTH:
        raise SnapshotRejected("signing_key_unavailable")

    snapshot = body.get("snapshot")
    signature = body.get("signature")
    if not isinstance(snapshot, dict) or not isinstance(signature, dict):
        raise SnapshotRejected("malformed")
    if signature.get("alg") != SIGNATURE_ALGORITHM or signature.get("kid") != key_id:
        raise SnapshotRejected("signature_invalid")
    value = signature.get("value")
    if not isinstance(value, str):
        raise SnapshotRejected("signature_invalid")
    expected = compute_signature(snapshot, signing_key)
    if not hmac.compare_digest(expected, value):
        raise SnapshotRejected("signature_invalid")

    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise SnapshotRejected("malformed")
    if snapshot.get("attested") is not True:
        raise SnapshotRejected("not_attested")
    if snapshot.get("organization_id") != str(organization_id):
        raise SnapshotRejected("wrong_organization")
    if snapshot.get("product_key") != product_key:
        raise SnapshotRejected("wrong_product")
    snapshot_id = snapshot.get("snapshot_id")
    subscription_status = snapshot.get("subscription_status")
    if not isinstance(snapshot_id, str) or not isinstance(subscription_status, str):
        raise SnapshotRejected("malformed")

    issued_at = _parse_instant(snapshot.get("issued_at"))
    expires_at = _parse_instant(snapshot.get("expires_at"))
    if issued_at > now + ISSUED_AT_SKEW:
        raise SnapshotRejected("not_yet_valid")
    if expires_at <= issued_at or expires_at - issued_at > MAX_SNAPSHOT_LIFETIME:
        raise SnapshotRejected("lifetime_invalid")
    if now >= expires_at:
        raise SnapshotRejected("expired")

    return VerifiedSnapshot(
        snapshot_id=snapshot_id,
        organization_id=organization_id,
        product_key=product_key,
        subscription_status=subscription_status,
        issued_at=issued_at,
        expires_at=expires_at,
        snapshot=snapshot,
        signature=value,
        key_id=key_id,
    )


def decide(verified: VerifiedSnapshot, *, feature_key: str) -> EntitlementVerdict:
    """Apply the shared entitlement rules to a verified organization snapshot."""
    entitlements = verified.snapshot.get("entitlements")
    access = {"subscription_status": verified.subscription_status, "entitlements": entitlements}
    return evaluate_feature_access(access, feature_key=feature_key, require_product_role=False)
