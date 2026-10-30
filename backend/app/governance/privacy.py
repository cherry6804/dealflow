"""Retention, legal holds, and export/deletion request records (DFR1-050).

What this module does:
- Versioned retention policy per data category.
- Legal holds that block deletion of a category until released.
- Deletion eligibility per category, with stable reason codes.
- Export and deletion request records with audited status changes.

What it does not do (documented as blocked in E13):
- It does not generate export artifacts. An export stays "awaiting_artifact_generation"
  until an artifact producer exists, and nothing is marked ready without one.
- It does not delete or anonymize data. A deletion request records eligibility only.
- It does not call external providers to delete their copies.
- It does not run automatic retention purges.

Every write is audited with the actor and the decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.governance.data_classification import CATEGORY_BY_KEY, is_customer_deletable

PRIVACY_EVENT_TYPE = "privacy"

REASON_CATEGORY_UNKNOWN = "category_unknown"
REASON_NOT_CUSTOMER_DELETABLE = "not_customer_deletable"
REASON_LEGAL_HOLD = "legal_hold_active"
REASON_NO_PRODUCER = "no_producer_yet"

STATUS_AWAITING_ARTIFACT = "awaiting_artifact_generation"
STATUS_READY = "ready"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_BLOCKED = "blocked"
STATUS_ELIGIBILITY_RECORDED = "eligibility_recorded"


class PrivacyError(Exception):
    """Base class for rule violations in the privacy workflows."""


class UnknownCategoryError(PrivacyError):
    pass


class InvalidRequestStateError(PrivacyError):
    pass


@dataclass(frozen=True)
class DeletionDecision:
    category_key: str
    eligible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _audit(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict,
    correlation_id: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=PRIVACY_EVENT_TYPE,
            action=action,
            decision="allowed",
            permission_key=None,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            event_metadata=json.dumps(metadata, sort_keys=True, default=str),
        )
    )


def _require_category(category_key: str) -> None:
    if category_key not in CATEGORY_BY_KEY:
        raise UnknownCategoryError(category_key)


def current_retention(db: Session, *, organization_id: UUID, category_key: str) -> RetentionPolicy | None:
    _require_category(category_key)
    return db.scalar(
        select(RetentionPolicy)
        .where(
            RetentionPolicy.organization_id == organization_id,
            RetentionPolicy.category_key == category_key,
        )
        .order_by(RetentionPolicy.version.desc())
        .limit(1)
    )


def set_retention_policy(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    category_key: str,
    retention_days: int | None,
) -> RetentionPolicy:
    """Create a new retention version. ``None`` means keep until a request or hold says otherwise."""
    _require_category(category_key)
    if retention_days is not None and (
        not isinstance(retention_days, int) or isinstance(retention_days, bool) or retention_days < 1
    ):
        raise ValueError("Retention days must be a positive integer or null.")
    previous = current_retention(db, organization_id=organization_id, category_key=category_key)
    version = (previous.version + 1) if previous is not None else 1
    policy = RetentionPolicy(
        organization_id=organization_id,
        category_key=category_key,
        retention_days=retention_days,
        version=version,
        changed_by_user_id=actor_user_id,
    )
    db.add(policy)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="privacy.retention.changed",
        resource_type="retention_policy",
        resource_id=category_key,
        metadata={
            "category_key": category_key,
            "retention_days": retention_days,
            "version": version,
        },
    )
    db.flush()
    return policy


def place_legal_hold(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    category_key: str,
    reason: str,
) -> LegalHold:
    _require_category(category_key)
    cleaned = reason.strip()
    if not cleaned:
        raise ValueError("A legal hold needs a reason.")
    hold = LegalHold(
        organization_id=organization_id,
        category_key=category_key,
        reason=cleaned[:500],
        placed_by_user_id=actor_user_id,
    )
    db.add(hold)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="privacy.legal_hold.placed",
        resource_type="legal_hold",
        resource_id=str(hold.id),
        metadata={"category_key": category_key, "reason": cleaned[:500]},
    )
    db.flush()
    return hold


def release_legal_hold(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    hold_id: UUID,
) -> LegalHold:
    hold = db.scalar(
        select(LegalHold).where(
            LegalHold.id == hold_id,
            LegalHold.organization_id == organization_id,
        )
    )
    if hold is None:
        raise InvalidRequestStateError("Legal hold not found.")
    if hold.released_at is not None:
        return hold
    hold.released_at = datetime.now(UTC)
    hold.released_by_user_id = actor_user_id
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="privacy.legal_hold.released",
        resource_type="legal_hold",
        resource_id=str(hold.id),
        metadata={"category_key": hold.category_key},
    )
    db.flush()
    return hold


def _active_hold(db: Session, *, organization_id: UUID, category_key: str) -> bool:
    return (
        db.scalar(
            select(LegalHold.id).where(
                LegalHold.organization_id == organization_id,
                LegalHold.category_key == category_key,
                LegalHold.released_at.is_(None),
            ).limit(1)
        )
        is not None
    )


def evaluate_deletion(db: Session, *, organization_id: UUID, category_key: str) -> DeletionDecision:
    """Return whether a category may be deleted on request, and every reason it may not."""
    category = CATEGORY_BY_KEY.get(category_key)
    if category is None:
        return DeletionDecision(category_key, False, (REASON_CATEGORY_UNKNOWN,))

    reasons: list[str] = []
    if not is_customer_deletable(category):
        reasons.append(REASON_NOT_CUSTOMER_DELETABLE)
    if _active_hold(db, organization_id=organization_id, category_key=category_key):
        reasons.append(REASON_LEGAL_HOLD)
    if not category.producer_exists:
        reasons.append(REASON_NO_PRODUCER)
    return DeletionDecision(category_key, not reasons, tuple(reasons))


def create_privacy_request(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    request_type: str,
    category_keys: list[str],
) -> PrivacyDataRequest:
    """Record an export or deletion request with per-category decisions. Does no processing."""
    if request_type not in {PrivacyDataRequest.TYPE_EXPORT, PrivacyDataRequest.TYPE_DELETION}:
        raise ValueError("Request type must be export or deletion.")
    if not category_keys:
        raise ValueError("Select at least one data category.")
    unique_keys = sorted(set(category_keys))
    for key in unique_keys:
        _require_category(key)

    if request_type == PrivacyDataRequest.TYPE_EXPORT:
        status = STATUS_AWAITING_ARTIFACT
        decisions: dict[str, object] = {key: {"included": True} for key in unique_keys}
    else:
        evaluated = [
            evaluate_deletion(db, organization_id=organization_id, category_key=key)
            for key in unique_keys
        ]
        decisions = {
            item.category_key: {"eligible": item.eligible, "reasons": list(item.reasons)}
            for item in evaluated
        }
        status = (
            STATUS_ELIGIBILITY_RECORDED
            if any(item.eligible for item in evaluated)
            else STATUS_BLOCKED
        )

    request = PrivacyDataRequest(
        organization_id=organization_id,
        request_type=request_type,
        status=status,
        categories=json.dumps(unique_keys),
        decisions=json.dumps(decisions, sort_keys=True),
        requested_by_user_id=actor_user_id,
    )
    db.add(request)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=f"privacy.{request_type}.requested",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"categories": unique_keys, "status": status, "decisions": decisions},
    )
    db.flush()
    return request


def _request_for(db: Session, *, organization_id: UUID, request_id: UUID) -> PrivacyDataRequest:
    request = db.scalar(
        select(PrivacyDataRequest).where(
            PrivacyDataRequest.id == request_id,
            PrivacyDataRequest.organization_id == organization_id,
        )
    )
    if request is None:
        raise InvalidRequestStateError("Privacy request not found.")
    return request


def mark_export_ready(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
    artifact_reference: str,
    expires_at: datetime,
) -> PrivacyDataRequest:
    """Attach a generated artifact. Only an export that is awaiting generation can become ready."""
    request = _request_for(db, organization_id=organization_id, request_id=request_id)
    if request.request_type != PrivacyDataRequest.TYPE_EXPORT:
        raise InvalidRequestStateError("Only export requests have artifacts.")
    if request.status != STATUS_AWAITING_ARTIFACT:
        raise InvalidRequestStateError(f"Export is {request.status}.")
    if not artifact_reference.strip():
        raise ValueError("An artifact reference is required.")
    request.status = STATUS_READY
    request.artifact_reference = artifact_reference.strip()[:500]
    request.expires_at = expires_at
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="privacy.export.ready",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"expires_at": expires_at.isoformat()},
    )
    db.flush()
    return request


def cancel_request(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
) -> PrivacyDataRequest:
    request = _request_for(db, organization_id=organization_id, request_id=request_id)
    if request.status not in {STATUS_AWAITING_ARTIFACT, STATUS_ELIGIBILITY_RECORDED, STATUS_READY}:
        raise InvalidRequestStateError(f"Request is {request.status} and cannot be cancelled.")
    request.status = STATUS_CANCELLED
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=f"privacy.{request.request_type}.cancelled",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={},
    )
    db.flush()
    return request


def expire_export_if_due(db: Session, *, request: PrivacyDataRequest, now: datetime) -> PrivacyDataRequest:
    """Expire a ready export whose download window has passed. Idempotent."""
    if request.status == STATUS_READY and request.expires_at is not None and request.expires_at <= now:
        request.status = STATUS_EXPIRED
        request.artifact_reference = None
        db.flush()
    return request
