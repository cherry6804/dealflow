"""AI entitlement from SIBVO's organization-level snapshot (WS5, ADR-0027, ADR-0029).

Used by every AI execution decision, synchronous or background. It never authorizes from an expired
snapshot. Refresh runs under an advisory lock per organization and product, so concurrent decisions
produce one SIBVO call. If SIBVO cannot refresh, the decision is a denial. A failed refresh opens a
backoff window (5 s doubling, capped at 300 s). That window only limits how often SIBVO is asked again.
It never extends authorization.

Reason codes returned here are new and stable:
- ``snapshot_missing``: no snapshot has ever been obtained, and SIBVO could not provide one now.
- ``snapshot_expired``: the stored snapshot has expired, and no fresh one could be obtained.
- ``snapshot_unavailable``: SIBVO could not be reached or failed to answer.
- ``snapshot_rejected``: SIBVO answered, but the response failed verification.
- ``organization_access_denied``: SIBVO reports no current access for this organization.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
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
REASON_ORGANIZATION_ACCESS_DENIED = "organization_access_denied"

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
):
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
    key_id = settings.sibvo_org_snapshot_key_id
    signing_key = (
        settings.sibvo_org_snapshot_signing_key.get_secret_value()
        if settings.sibvo_org_snapshot_signing_key is not None
        else None
    )
    current = now or datetime.now(UTC)

    _lock(db, organization_id, product_key)
    row = _row(db, organization_id, product_key)

    # 1. A stored snapshot that still verifies and has not expired is the only grant path.
    if row is not None:
        verified = _verified_from_row(
            row,
            organization_id=organization_id,
            product_key=product_key,
            signing_key=signing_key,
            key_id=key_id,
            now=current,
        )
        if verified is not None:
            return decide(verified, feature_key=feature_key)

    # 2. Expired or missing. Respect the backoff window: do not ask SIBVO again yet, and deny.
    if row is not None and row.next_refresh_attempt_at is not None and current < row.next_refresh_attempt_at:
        return _deny(REASON_SNAPSHOT_EXPIRED if row.expires_at is not None else REASON_SNAPSHOT_MISSING)

    # 3. Refresh from SIBVO over the authenticated service contract.
    try:
        body = fetch_organization_entitlements(settings, organization_id)
    except (SibvoUnavailable, SibvoRejected, SibvoRequestDenied, SibvoInvalidResponse):
        _record_failure(db, organization_id, product_key, current)
        db.flush()
        return _deny(REASON_SNAPSHOT_UNAVAILABLE)

    try:
        verified = verify_snapshot(
            body,
            signing_key=signing_key,
            key_id=key_id,
            organization_id=organization_id,
            product_key=product_key,
            now=current,
        )
    except SibvoDenied:
        # SIBVO says no current access. Remove any grant held from an earlier snapshot.
        row = _ensure_row(db, organization_id, product_key)
        row.snapshot_body = None
        row.expires_at = current
        row.issued_at = None
        row.fetched_at = current
        row.failure_count = 0
        row.next_refresh_attempt_at = None
        db.flush()
        return _deny(REASON_ORGANIZATION_ACCESS_DENIED)
    except SnapshotRejected as exc:
        # A response that fails verification never replaces the stored snapshot.
        _record_failure(db, organization_id, product_key, current)
        db.flush()
        return _deny(REASON_SNAPSHOT_REJECTED if exc.reason != "signing_key_unavailable" else REASON_SNAPSHOT_UNAVAILABLE)

    row = _ensure_row(db, organization_id, product_key)
    row.snapshot_body = body
    row.issued_at = verified.issued_at
    row.expires_at = verified.expires_at
    row.fetched_at = current
    row.failure_count = 0
    row.next_refresh_attempt_at = None
    db.flush()
    return decide(verified, feature_key=feature_key)


__all__ = [
    "REASON_ENTITLEMENT_ALLOWED",
    "REASON_ORGANIZATION_ACCESS_DENIED",
    "REASON_SNAPSHOT_EXPIRED",
    "REASON_SNAPSHOT_MISSING",
    "REASON_SNAPSHOT_REJECTED",
    "REASON_SNAPSHOT_UNAVAILABLE",
    "organization_entitlement_verdict",
]
