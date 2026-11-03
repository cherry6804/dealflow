"""Human approval lifecycle for exact payloads (DFR1-006, ADR-0029 gate 5).

Lifecycle: ``pending`` -> ``approved`` or ``rejected`` (by another member) or ``expired`` (time ran out before a
decision). An ``approved`` request is consumed once, by the execution it authorized. Consumption is recorded and
can never be repeated.

Binding: an approval covers one capability, one resource and the SHA-256 hash of one canonical payload. A changed
payload hashes differently and cannot use an existing approval. Each consume checks the row under a row lock, so
two executions racing for one approval cannot both succeed.

Every transition writes an audit event in the caller's transaction. Audit metadata holds the capability,
the resource, the status and the payload hash. It never holds the payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.approval_request import ApprovalRequest
from app.db.models.audit_event import AuditEvent
from app.governance.capabilities import CAPABILITY_BY_KEY

APPROVAL_AUDIT_EVENT_TYPE = "governance"
APPROVAL_AUDIT_ACTION_PREFIX = "approval"
PERMISSION_REQUEST = "governance.approvals.request"
PERMISSION_DECIDE = "governance.approvals.decide"

MIN_TTL = timedelta(minutes=1)
MAX_TTL = timedelta(days=7)
MAX_PAYLOAD_BYTES = 64 * 1024

REASON_APPROVAL_REQUIRED = "approval_required"
REASON_APPROVAL_NOT_FOUND = "approval_not_found"
REASON_APPROVAL_NOT_APPROVED = "approval_not_approved"
REASON_APPROVAL_EXPIRED = "approval_expired"
REASON_APPROVAL_ALREADY_USED = "approval_already_used"
REASON_APPROVAL_MISMATCH = "approval_mismatch"
REASON_APPROVAL_NOT_PENDING = "approval_not_pending"
REASON_SELF_APPROVAL = "approval_self_decision_refused"


class ApprovalError(Exception):
    """An approval step was refused. ``reason_code`` is stable and safe to show."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ApprovalInvalidError(Exception):
    """A request to create an approval breaks a rule. The message is safe to show."""


def payload_hash(payload: Mapping[str, object]) -> str:
    """Hash the canonical JSON form of a payload. Key order and whitespace do not change the hash."""
    try:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ApprovalInvalidError("The payload must be JSON-serializable without NaN or Infinity.") from error
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ApprovalInvalidError("The payload is too large to approve.")
    return hashlib.sha256(encoded).hexdigest()


def _audit(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    approval: ApprovalRequest,
    now: datetime,
    permission_key: str,
    extra: dict[str, object] | None = None,
) -> None:
    metadata: dict[str, object] = {
        "capability_key": approval.capability_key,
        "status": approval.status,
        "payload_hash": approval.payload_hash,
    }
    metadata.update(extra or {})
    db.add(
        AuditEvent(
            occurred_at=now,
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=APPROVAL_AUDIT_EVENT_TYPE,
            action=f"{APPROVAL_AUDIT_ACTION_PREFIX}.{action}",
            decision="allowed",
            permission_key=permission_key,
            resource_type="approval_request",
            resource_id=str(approval.id),
            event_metadata=json.dumps(metadata, sort_keys=True),
        )
    )
    db.flush()


def _locked(db: Session, *, organization_id: UUID, approval_id: UUID) -> ApprovalRequest:
    """Load the approval under a row lock for the rest of the transaction. Another organization's ID is not found."""
    approval = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id, ApprovalRequest.organization_id == organization_id)
        .with_for_update()
    )
    if approval is None:
        raise ApprovalError(REASON_APPROVAL_NOT_FOUND)
    return approval


def request_approval(
    db: Session,
    *,
    organization_id: UUID,
    requester_user_id: UUID,
    capability_key: str,
    resource_type: str,
    resource_id: str,
    payload: Mapping[str, object],
    ttl: timedelta,
    now: datetime | None = None,
) -> ApprovalRequest:
    """Create a pending approval for one exact payload. Only capabilities that require approval may use it."""
    definition = CAPABILITY_BY_KEY.get(capability_key)
    if definition is None or not definition.requires_approval:
        raise ApprovalInvalidError("This capability does not use approvals.")
    if not MIN_TTL <= ttl <= MAX_TTL:
        raise ApprovalInvalidError("The approval must expire between one minute and seven days from now.")
    if not resource_id or len(resource_id) > 64 or len(resource_type) > 64:
        raise ApprovalInvalidError("The resource reference is invalid.")

    current = now if now is not None else datetime.now(UTC)
    approval = ApprovalRequest(
        organization_id=organization_id,
        capability_key=capability_key,
        resource_type=resource_type,
        resource_id=resource_id,
        payload_hash=payload_hash(payload),
        status="pending",
        requested_by_user_id=requester_user_id,
        requested_at=current,
        expires_at=current + ttl,
    )
    db.add(approval)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=requester_user_id,
        action="requested",
        approval=approval,
        now=current,
        permission_key=PERMISSION_REQUEST,
    )
    return approval


def decide_approval(
    db: Session,
    *,
    organization_id: UUID,
    approver_user_id: UUID,
    approval_id: UUID,
    approve: bool,
    now: datetime | None = None,
) -> ApprovalRequest:
    """Approve or reject a pending request. The requester can never decide their own request."""
    current = now if now is not None else datetime.now(UTC)
    approval = _locked(db, organization_id=organization_id, approval_id=approval_id)
    if approval.status != "pending":
        raise ApprovalError(REASON_APPROVAL_NOT_PENDING)
    if current >= approval.expires_at:
        approval.status = "expired"
        db.flush()
        _audit(
            db,
            organization_id=organization_id,
            actor_user_id=approver_user_id,
            action="expired",
            approval=approval,
            now=current,
            permission_key=PERMISSION_DECIDE,
        )
        raise ApprovalError(REASON_APPROVAL_EXPIRED)
    if approver_user_id == approval.requested_by_user_id:
        raise ApprovalError(REASON_SELF_APPROVAL)

    approval.status = "approved" if approve else "rejected"
    approval.decided_by_user_id = approver_user_id
    approval.decided_at = current
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=approver_user_id,
        action="approved" if approve else "rejected",
        approval=approval,
        now=current,
        permission_key=PERMISSION_DECIDE,
    )
    return approval


def check_approval_for_execution(
    db: Session,
    *,
    organization_id: UUID,
    approval_id: UUID,
    capability_key: str,
    resource_type: str,
    resource_id: str,
    payload: Mapping[str, object],
    now: datetime | None = None,
) -> ApprovalRequest:
    """Check that an approval covers this exact execution. Locks the row; call ``consume_approval`` before commit."""
    current = now if now is not None else datetime.now(UTC)
    approval = _locked(db, organization_id=organization_id, approval_id=approval_id)
    if approval.consumed_at is not None:
        raise ApprovalError(REASON_APPROVAL_ALREADY_USED)
    if approval.status != "approved":
        raise ApprovalError(REASON_APPROVAL_NOT_APPROVED)
    if current >= approval.expires_at:
        raise ApprovalError(REASON_APPROVAL_EXPIRED)
    if (
        approval.capability_key != capability_key
        or approval.resource_type != resource_type
        or approval.resource_id != resource_id
    ):
        raise ApprovalError(REASON_APPROVAL_MISMATCH)
    try:
        current_hash = payload_hash(payload)
    except ApprovalInvalidError as error:
        raise ApprovalError(REASON_APPROVAL_MISMATCH) from error
    if current_hash != approval.payload_hash:
        raise ApprovalError(REASON_APPROVAL_MISMATCH)
    return approval


def consume_approval(
    db: Session,
    *,
    organization_id: UUID,
    approval_id: UUID,
    actor_user_id: UUID | None,
    now: datetime | None = None,
) -> ApprovalRequest:
    """Mark an approved request as used. Must follow a successful ``check_approval_for_execution`` in the same transaction."""
    current = now if now is not None else datetime.now(UTC)
    approval = _locked(db, organization_id=organization_id, approval_id=approval_id)
    if approval.consumed_at is not None or approval.status != "approved":
        raise ApprovalError(REASON_APPROVAL_ALREADY_USED)
    approval.consumed_at = current
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="consumed",
        approval=approval,
        now=current,
        permission_key=PERMISSION_REQUEST,
    )
    return approval


def list_approvals(db: Session, *, organization_id: UUID) -> list[ApprovalRequest]:
    return list(
        db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.organization_id == organization_id)
            .order_by(ApprovalRequest.requested_at.desc())
        ).all()
    )
