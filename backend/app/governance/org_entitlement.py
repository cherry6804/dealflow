"""AI entitlement from SIBVO's organization-level snapshot (WS5, ADR-0027, ADR-0029, WS6 WP6).

Used by every AI execution decision, synchronous or background. It never authorizes from an expired
snapshot. Refresh runs under an advisory lock per organization and product, so concurrent decisions
produce one SIBVO call, and no refresh starts while another is still running.

Revalidation (WS6 WP6):

- A stored snapshot is served from the cache until it is due for revalidation, which is
  ``sibvo_org_entitlement_revalidation_seconds`` after its last fetch (default 30 seconds). A snapshot is
  valid for at most 30 seconds, so a due snapshot is usually also at or near expiry.
- When a snapshot is due and SIBVO cannot be reached, the decision uses the stored snapshot only while it
  has not expired. After expiry, the decision is a denial.
- An answer older than the stored snapshot never replaces it.
- Backoff after a failed refresh is 5 seconds doubling, capped at 300 seconds. Backoff limits how often
  SIBVO is asked again. It never extends authorization.

Reason codes returned here are stable:
- ``snapshot_missing``: no snapshot has ever been obtained, and SIBVO could not provide one now.
- ``snapshot_expired``: the stored snapshot has expired, and no fresh one could be obtained.
- ``snapshot_unavailable``: SIBVO could not be reached or failed to answer.
- ``snapshot_rejected``: SIBVO answered, but the response failed verification.
- ``snapshot_stale``: SIBVO answered with an older snapshot than the one already stored.
- ``organization_access_denied``: SIBVO reports no current access for this organization.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models.organization_entitlement_snapshot import (
    OrganizationEntitlementSnapshot,
)
from app.governance.entitlement import (
    REASON_ENTITLEMENT_ALLOWED,
    EntitlementVerdict,
)
from app.integrations.org_entitlement_snapshot import (
    SibvoDenied,
    SnapshotRejected,
    VerifiedSnapshot,
    decide,
    verify_snapshot,
)
from app.integrations.sibvo_client import (
    SibvoInvalidResponse,
    SibvoRejected,
    SibvoRequestDenied,
    SibvoUnavailable,
    fetch_organization_entitlements,
)

REASON_SNAPSHOT_MISSING = "snapshot_missing"
REASON_SNAPSHOT_EXPIRED = "snapshot_expired"
REASON_SNAPSHOT_UNAVAILABLE = "snapshot_unavailable"
REASON_SNAPSHOT_REJECTED = "snapshot_rejected"
REASON_SNAPSHOT_STALE = "snapshot_stale"
REASON_ORGANIZATION_ACCESS_DENIED = "organization_access_denied"

logger = logging.getLogger(__name__)

BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 300


def _deny(reason: str) -> EntitlementVerdict:
    return EntitlementVerdict(False, reason)


def _lock(db: Session, organization_id: UUID, product_key: str) -> None:
    """Serialize refreshes for one organization and product until the transaction ends."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"org-entitlement:{organization_id}:{product_key}"},
    )


def _row(db: Session, organization_id: UUID, product_key: str) -> OrganizationEntitlementSnapshot | None:
    return db.scalar(
        select(OrganizationEntitlementSnapshot).where(
            OrganizationEntitlementSnapshot.organization_id == organization_id,
            OrganizationEntitlementSnapshot.product_key == product_key,
        )
    )


def _ensure_row(db: Session, organization_id: UUID, product_key: str) -> OrganizationEntitlementSnapshot:
    row = _row(db, organization_id, product_key)
    if row is None:
        row = OrganizationEntitlementSnapshot(
            organization_id=organization_id,
            product_key=product_key,
            failure_count=0,
        )
        db.add(row)
        db.flush()
    return row


def _record_failure(db: Session, organization_id: UUID, product_key: str, now: datetime) -> None:
    row = _ensure_row(db, organization_id, product_key)
    row.failure_count += 1
    delay = min(BACKOFF_BASE_SECONDS * (2 ** (row.failure_count - 1)), BACKOFF_MAX_SECONDS)
    row.next_refresh_attempt_at = now + timedelta(seconds=delay)


def _verified_from_row(
    row: OrganizationEntitlementSnapshot,
    *,
    organization_id: UUID,
    product_key: str,
    signing_key: str | None,
    key_id: str,
    now: datetime,
) -> VerifiedSnapshot | None:
    if row.snapshot_body is None or row.expires_at is None:
        return None
    try:
        return verify_snapshot(
            row.snapshot_body,
            signing_key=signing_key,
            key_id=key_id,
            organization_id=organization_id,
            product_key=product_key,
            now=now,
        )
    except (SnapshotRejected, SibvoDenied):
        return None


def _revalidation_due(row: OrganizationEntitlementSnapshot, *, now: datetime, interval_seconds: int) -> bool:
    if row.fetched_at is None:
        return True
    return now >= row.fetched_at + timedelta(seconds=interval_seconds)


def _has_expired_snapshot(row: OrganizationEntitlementSnapshot | None, *, now: datetime) -> bool:
    """A stored snapshot exists and its validity has ended. Only then is the reason "expired".

    A snapshot that never verified, or that SIBVO's denial removed, is reported as missing or unavailable.
    """
    return (
        row is not None
        and row.snapshot_body is not None
        and row.expires_at is not None
        and now >= row.expires_at
    )


def _no_snapshot_reason(row: OrganizationEntitlementSnapshot | None, *, now: datetime) -> str:
    return REASON_SNAPSHOT_EXPIRED if _has_expired_snapshot(row, now=now) else REASON_SNAPSHOT_MISSING


def _in_backoff(row: OrganizationEntitlementSnapshot | None, *, now: datetime) -> bool:
    return row is not None and row.next_refresh_attempt_at is not None and now < row.next_refresh_attempt_at


def _log_refresh_failure(organization_id: UUID, reason: str, *, detail: str | None = None) -> None:
    """Record why SIBVO's answer was not used. Authorization still reports its own reason code.

    The log carries the organization and stable codes only, never a body, signature, key or message text.
    """
    logger.warning(
        "org_entitlement_refresh_failed",
        extra={"organization_id": str(organization_id), "refresh_reason": reason, "refresh_detail": detail},
    )


def _signing_key(settings: Settings) -> str | None:
    return (
        settings.sibvo_org_snapshot_signing_key.get_secret_value()
        if settings.sibvo_org_snapshot_signing_key is not None
        else None
    )


def _refresh(
    db: Session,
    *,
    organization_id: UUID,
    product_key: str,
    feature_key: str,
    now: datetime,
    settings: Settings,
    signing_key: str | None,
) -> tuple[EntitlementVerdict, bool]:
    """Ask SIBVO and store a verified answer. Returns ``(verdict, refreshed)``.

    ``refreshed`` is True when SIBVO's answer is authoritative and stored, including an explicit denial.
    It is False when SIBVO failed or its answer was rejected or stale. The caller then decides from the
    stored snapshot, if one is still valid, and otherwise denies.
    """
    key_id = settings.sibvo_org_snapshot_key_id
    try:
        body = fetch_organization_entitlements(settings, organization_id)
    except (SibvoUnavailable, SibvoRejected, SibvoRequestDenied, SibvoInvalidResponse):
        _record_failure(db, organization_id, product_key, now)
        db.flush()
        _log_refresh_failure(organization_id, REASON_SNAPSHOT_UNAVAILABLE)
        return _deny(REASON_SNAPSHOT_UNAVAILABLE), False

    try:
        verified = verify_snapshot(
            body,
            signing_key=signing_key,
            key_id=key_id,
            organization_id=organization_id,
            product_key=product_key,
            now=now,
        )
    except SibvoDenied:
        # SIBVO says no current access. Remove any grant held from an earlier snapshot.
        row = _ensure_row(db, organization_id, product_key)
        row.snapshot_body = None
        row.expires_at = now
        row.issued_at = None
        row.fetched_at = now
        row.failure_count = 0
        row.next_refresh_attempt_at = None
        db.flush()
        return _deny(REASON_ORGANIZATION_ACCESS_DENIED), True
    except SnapshotRejected as exc:
        # A response that fails verification never replaces the stored snapshot.
        _record_failure(db, organization_id, product_key, now)
        db.flush()
        reason = REASON_SNAPSHOT_UNAVAILABLE if exc.reason == "signing_key_unavailable" else REASON_SNAPSHOT_REJECTED
        _log_refresh_failure(organization_id, reason, detail=exc.reason)
        return _deny(reason), False

    row = _ensure_row(db, organization_id, product_key)
    if row.issued_at is not None and verified.issued_at < row.issued_at:
        # An older answer never replaces a newer snapshot, even when it verifies (WS6 WP6). The stored
        # snapshot remains the authority, and the caller decides from it.
        _log_refresh_failure(organization_id, REASON_SNAPSHOT_STALE)
        return _deny(REASON_SNAPSHOT_STALE), False

    row.snapshot_body = body
    row.issued_at = verified.issued_at
    row.expires_at = verified.expires_at
    row.fetched_at = now
    row.failure_count = 0
    row.next_refresh_attempt_at = None
    db.flush()
    return decide(verified, feature_key=feature_key), True


def organization_entitlement_verdict(
    db: Session,
    *,
    organization_id: UUID,
    feature_key: str,
    now: datetime | None = None,
) -> EntitlementVerdict:
    """Return whether SIBVO's current organization snapshot allows ``feature_key``.

    The caller owns the transaction. Refresh writes are flushed, and the caller commits them.
    """
    settings = get_settings()
    product_key = settings.sso_dealsflo_product_key
    signing_key = _signing_key(settings)
    current = now or datetime.now(UTC)

    _lock(db, organization_id, product_key)
    row = _row(db, organization_id, product_key)

    stored: VerifiedSnapshot | None = None
    if row is not None:
        stored = _verified_from_row(
            row,
            organization_id=organization_id,
            product_key=product_key,
            signing_key=signing_key,
            key_id=settings.sibvo_org_snapshot_key_id,
            now=current,
        )

    # 1. A stored snapshot that still verifies and is not due for revalidation is served from the cache.
    if stored is not None and not _revalidation_due(
        row, now=current, interval_seconds=settings.sibvo_org_entitlement_revalidation_seconds
    ):
        return decide(stored, feature_key=feature_key)

    # 2. Backoff after a failed refresh. Do not ask SIBVO again yet. A still-valid snapshot may be used.
    if _in_backoff(row, now=current):
        if stored is not None:
            return decide(stored, feature_key=feature_key)
        return _deny(_no_snapshot_reason(row, now=current))

    # 3. Refresh from SIBVO over the authenticated service contract.
    verdict, refreshed = _refresh(
        db,
        organization_id=organization_id,
        product_key=product_key,
        feature_key=feature_key,
        now=current,
        settings=settings,
        signing_key=signing_key,
    )
    if refreshed:
        return verdict
    if stored is None:
        # SIBVO could not provide a snapshot. An expired stored snapshot is reported as expired even though
        # SIBVO is unreachable (WS6 WP6). The SIBVO failure itself is logged above.
        if _has_expired_snapshot(row, now=current):
            return _deny(REASON_SNAPSHOT_EXPIRED)
        return verdict
    # The refresh failed, but the stored snapshot has not expired, so it still authorizes.
    return decide(stored, feature_key=feature_key)


def snapshot_diagnostics(
    db: Session,
    *,
    organization_id: UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Operational state for one organization's snapshot. Never returns the body, signature or key."""
    settings = get_settings()
    product_key = settings.sso_dealsflo_product_key
    current = now or datetime.now(UTC)
    interval = settings.sibvo_org_entitlement_revalidation_seconds
    row = _row(db, organization_id, product_key)

    def instant(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    state = "missing"
    if row is not None:
        valid = _verified_from_row(
            row,
            organization_id=organization_id,
            product_key=product_key,
            signing_key=_signing_key(settings),
            key_id=settings.sibvo_org_snapshot_key_id,
            now=current,
        )
        if valid is not None:
            due = _revalidation_due(row, now=current, interval_seconds=interval)
            state = "due_for_revalidation" if due else "valid"
        elif row.expires_at is not None and current >= row.expires_at:
            state = "expired"

    return {
        "state": state,
        "product_key": product_key,
        "revalidation_interval_seconds": interval,
        "fetched_at": instant(row.fetched_at) if row else None,
        "expires_at": instant(row.expires_at) if row else None,
        "failure_count": row.failure_count if row else 0,
        "next_refresh_attempt_at": instant(row.next_refresh_attempt_at) if row else None,
        "backoff_active": _in_backoff(row, now=current),
    }


__all__ = [
    "REASON_ENTITLEMENT_ALLOWED",
    "REASON_ORGANIZATION_ACCESS_DENIED",
    "REASON_SNAPSHOT_EXPIRED",
    "REASON_SNAPSHOT_MISSING",
    "REASON_SNAPSHOT_REJECTED",
    "REASON_SNAPSHOT_STALE",
    "REASON_SNAPSHOT_UNAVAILABLE",
    "organization_entitlement_verdict",
    "snapshot_diagnostics",
]
