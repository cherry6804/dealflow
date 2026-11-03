"""Centralized execution gate for governed AI and automation (DFR1-006).

Every governed execution calls ``authorize_execution`` before it does work, and again before each
further step of the same run (in-flight revalidation). The gate combines:

1. An actor is present, belongs to the organization, and has an active membership.
2. The target resource belongs to the organization and is active (published and not paused).
3. The capability policy allows it (``app.governance.policy.evaluate_capability``): plan feature,
   organization switches, approval, provider and consent. Each of these fails closed.
4. Billable work is denied until the usage budget gate exists (DFR1-017).
5. The actor holds the permission for the action, checked through the existing permission lookup.

It writes one audit record for every decision, allowed or denied, in the caller's transaction.
The record holds the actor, organization, capability, resource, stage and reason code. It holds no
payload or personal data.

This module is the only place that turns a capability decision into an execution decision. Callers
must not evaluate the policy directly for execution.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext
from app.authz.dependencies import permission_granted
from app.db.models.audit_event import AuditDecision, AuditEvent
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.governance.approvals import (
    ApprovalError,
    check_approval_for_execution,
    consume_approval,
)
from app.governance.capabilities import CAPABILITY_BY_KEY
from app.governance.channel_policy import evaluate_channel_policy
from app.governance.consent import (
    EFFECTIVE_EXPIRED,
    EFFECTIVE_GRANTED,
    EFFECTIVE_REVOKED,
    ConsentSubject,
    current_consent,
)
from app.governance.policy import PolicyDecision, evaluate_capability
from app.governance.usage_ledger import (
    BudgetExceededError,
    BudgetNotConfiguredError,
    IdempotencyConflictError,
    UsageUnit,
    reserve,
)
from app.tenant.dependencies import TenantContext

GOVERNANCE_AUDIT_EVENT_TYPE = "governance"
EXECUTION_AUDIT_ACTION = "capability.execution"

REASON_ACTOR_REQUIRED = "actor_required"
REASON_WRONG_ORGANIZATION = "wrong_organization"
REASON_MEMBERSHIP_INACTIVE = "membership_inactive"
REASON_TARGET_ORGANIZATION_MISMATCH = "target_organization_mismatch"
REASON_RESOURCE_NOT_ACTIVE = "resource_not_active"
REASON_ACTOR_NOT_AUTHORIZED = "actor_not_authorized"
REASON_BUDGET_RESERVATION_REQUIRED = "budget_reservation_required"
REASON_BUDGET_NOT_CONFIGURED = "budget_not_configured"
REASON_BUDGET_EXHAUSTED = "budget_exhausted"
REASON_USAGE_KEY_CONFLICT = "usage_key_conflict"
REASON_CONSENT_MISSING = "consent_missing"
REASON_CONSENT_REVOKED = "consent_revoked"
REASON_CONSENT_EXPIRED = "consent_expired"
REASON_CONSENT_CHANNEL_MISMATCH = "consent_channel_mismatch"
REASON_CHANNEL_NOT_CONFIGURED = "channel_policy_not_configured"
REASON_CHANNEL_DISABLED = "channel_disabled"
REASON_CONTACT_DO_NOT_DISTURB = "contact_do_not_disturb"
REASON_OUTSIDE_MESSAGING_WINDOW = "outside_messaging_window"
REASON_QUIET_HOURS = "quiet_hours"
REASON_APPROVAL_REQUIRED = "approval_required"
REASON_APPROVAL_NOT_FOUND = "approval_not_found"
REASON_APPROVAL_NOT_APPROVED = "approval_not_approved"
REASON_APPROVAL_EXPIRED = "approval_expired"
REASON_APPROVAL_ALREADY_USED = "approval_already_used"
REASON_APPROVAL_MISMATCH = "approval_mismatch"
REASON_ALLOWED = "allowed"

_EXPLANATIONS: dict[str, str] = {
    REASON_ACTOR_REQUIRED: "Automation runs only on behalf of an authenticated user.",
    REASON_WRONG_ORGANIZATION: "Your session is not authorized for this organization.",
    REASON_MEMBERSHIP_INACTIVE: "Your membership in this organization is not active.",
    REASON_TARGET_ORGANIZATION_MISMATCH: "The record does not belong to this organization.",
    REASON_RESOURCE_NOT_ACTIVE: "This automation is not published and active.",
    REASON_ACTOR_NOT_AUTHORIZED: "You do not have permission for this action.",
    REASON_BUDGET_RESERVATION_REQUIRED: (
        "Billable AI work must reserve usage budget before it runs."
    ),
    REASON_BUDGET_NOT_CONFIGURED: (
        "No usage budget is configured for this period, so billable AI work cannot run."
    ),
    REASON_BUDGET_EXHAUSTED: "The usage budget for this period is used up.",
    REASON_USAGE_KEY_CONFLICT: (
        "This usage reservation key was already used for a different request."
    ),
    REASON_CONSENT_MISSING: "The contact has not given consent for this channel and purpose.",
    REASON_CONSENT_REVOKED: "The contact has withdrawn consent for this channel and purpose.",
    REASON_CONSENT_EXPIRED: "The contact's consent for this channel and purpose has expired.",
    REASON_CONSENT_CHANNEL_MISMATCH: "The consent channel does not match this capability.",
    REASON_CHANNEL_NOT_CONFIGURED: "No channel policy is configured for this channel, so it cannot be used.",
    REASON_CHANNEL_DISABLED: "This channel is turned off for the organization.",
    REASON_CONTACT_DO_NOT_DISTURB: "This contact has asked not to be contacted.",
    REASON_OUTSIDE_MESSAGING_WINDOW: "The current time is outside the messaging window for this channel.",
    REASON_QUIET_HOURS: "The current time is within the quiet hours for this channel.",
    REASON_APPROVAL_REQUIRED: "This action needs a human approval of its exact payload before it can run.",
    REASON_APPROVAL_NOT_FOUND: "The approval does not exist in this organization.",
    REASON_APPROVAL_NOT_APPROVED: "The approval has not been granted.",
    REASON_APPROVAL_EXPIRED: "The approval has expired. Request a new one.",
    REASON_APPROVAL_ALREADY_USED: "The approval was already used. Each approval covers one execution.",
    REASON_APPROVAL_MISMATCH: "The approval does not cover this exact action and payload.",
    REASON_ALLOWED: "The execution is allowed.",
}


@dataclass(frozen=True)
class BudgetReservation:
    """Usage the execution needs. The gate reserves it, and the caller settles or releases it."""

    unit: UsageUnit | str
    quantity: int
    idempotency_key: str


@dataclass(frozen=True)
class ExecutionRequest:
    """One proposed execution, with everything the gate needs to decide."""

    organization_id: UUID
    capability_key: str
    actor: CurrentUserContext | None
    resource_type: str
    resource_id: str
    resource_organization_id: UUID
    resource_active: bool
    required_permission: str | None
    billable: bool = False
    budget: BudgetReservation | None = None
    # Required for capabilities that need consent. The gate checks this contact's current consent.
    consent: ConsentSubject | None = None
    # Required for capabilities that need approval: the approval ID and the exact payload it covers.
    approval_id: UUID | None = None
    payload: Mapping[str, object] | None = None
    # ``initial`` before the first step, ``revalidation`` before each later step.
    stage: str = "initial"
    correlation_id: str | None = None


def _denied(request: ExecutionRequest, reason_code: str, policy_version: int = 0) -> PolicyDecision:
    return PolicyDecision(
        capability_key=request.capability_key,
        organization_id=request.organization_id,
        allowed=False,
        reason_code=reason_code,
        explanation=_EXPLANATIONS[reason_code],
        policy_version=policy_version,
        correlation_id=request.correlation_id,
    )


def _actor_membership(db: Session, request: ExecutionRequest) -> Membership | None:
    actor = request.actor
    if actor is None:
        return None
    return db.scalar(
        select(Membership).where(
            Membership.user_id == actor.user_id,
            Membership.organization_id == request.organization_id,
            Membership.is_active.is_(True),
        )
    )


def _check_channel(db: Session, request: ExecutionRequest, policy_version: int) -> PolicyDecision | None:
    """Apply the organization's channel policy and the contact's do-not-disturb flag to a channel send."""
    subject = request.consent
    assert subject is not None  # channel capabilities require consent, so the policy denied without a subject
    channel = request.capability_key.split(".")[-1]
    reason = evaluate_channel_policy(
        db,
        organization_id=request.organization_id,
        channel=channel,
        contact_id=subject.contact_id,
    )
    if reason is None:
        return None
    return _denied(request, reason, policy_version)


def _check_approval(db: Session, request: ExecutionRequest, policy_version: int) -> PolicyDecision | None:
    """Confirm that the approval covers this exact execution. The row stays locked until the transaction ends."""
    assert request.approval_id is not None
    if request.payload is None:
        return _denied(request, REASON_APPROVAL_MISMATCH, policy_version)
    try:
        check_approval_for_execution(
            db,
            organization_id=request.organization_id,
            approval_id=request.approval_id,
            capability_key=request.capability_key,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            payload=request.payload,
        )
    except ApprovalError as error:
        return _denied(request, error.reason_code, policy_version)
    return None


def _evaluate(db: Session, request: ExecutionRequest) -> PolicyDecision:
    if request.actor is None:
        return _denied(request, REASON_ACTOR_REQUIRED)
    if request.actor.session_organization_id != request.organization_id:
        return _denied(request, REASON_WRONG_ORGANIZATION)

    membership = _actor_membership(db, request)
    if membership is None:
        return _denied(request, REASON_MEMBERSHIP_INACTIVE)

    if request.resource_organization_id != request.organization_id:
        return _denied(request, REASON_TARGET_ORGANIZATION_MISMATCH)
    if not request.resource_active:
        return _denied(request, REASON_RESOURCE_NOT_ACTIVE)

    policy = evaluate_capability(
        db,
        organization_id=request.organization_id,
        capability_key=request.capability_key,
        user_context=request.actor,
        correlation_id=request.correlation_id,
        consent_checked=request.consent is not None,
        approval_checked=request.approval_id is not None,
    )
    if not policy.allowed:
        return policy

    if CAPABILITY_BY_KEY[request.capability_key].requires_consent:
        consent_refusal = _check_consent(db, request, policy.policy_version)
        if consent_refusal is not None:
            return consent_refusal

    if request.capability_key.startswith("channels."):
        channel_refusal = _check_channel(db, request, policy.policy_version)
        if channel_refusal is not None:
            return channel_refusal

    if request.required_permission is not None:
        organization = db.get(Organization, request.organization_id)
        if organization is None:
            return _denied(request, REASON_WRONG_ORGANIZATION)
        tenant = TenantContext(organization=organization, membership=membership)
        if not permission_granted(
            db, tenant_context=tenant, permission_key=request.required_permission
        ):
            return _denied(request, REASON_ACTOR_NOT_AUTHORIZED, policy.policy_version)

    if CAPABILITY_BY_KEY[request.capability_key].requires_approval:
        approval_refusal = _check_approval(db, request, policy.policy_version)
        if approval_refusal is not None:
            return approval_refusal

    if request.billable:
        # Budget is reserved last, after every other check, so a refused execution never holds usage.
        if request.budget is None:
            return _denied(request, REASON_BUDGET_RESERVATION_REQUIRED, policy.policy_version)
        reservation_refusal = _reserve_budget(db, request, policy.policy_version)
        if reservation_refusal is not None:
            return reservation_refusal

    if CAPABILITY_BY_KEY[request.capability_key].requires_approval:
        # Consumed last, so a refusal anywhere above leaves the approval unused. Nothing else runs in between.
        assert request.approval_id is not None  # the policy denies approval-requiring work without one
        consume_approval(
            db,
            organization_id=request.organization_id,
            approval_id=request.approval_id,
            actor_user_id=request.actor.user_id if request.actor is not None else None,
        )

    return PolicyDecision(
        capability_key=request.capability_key,
        organization_id=request.organization_id,
        allowed=True,
        reason_code=REASON_ALLOWED,
        explanation=_EXPLANATIONS[REASON_ALLOWED],
        policy_version=policy.policy_version,
        correlation_id=request.correlation_id,
    )


def _check_consent(db: Session, request: ExecutionRequest, policy_version: int) -> PolicyDecision | None:
    """Read the contact's consent now. Revocation takes effect on the very next execution."""
    subject = request.consent
    assert subject is not None  # the policy denies consent-requiring capabilities without a subject
    expected_channel = request.capability_key.split(".")[-1] if request.capability_key.startswith("channels.") else None
    if expected_channel is not None and subject.channel != expected_channel:
        return _denied(request, REASON_CONSENT_CHANNEL_MISMATCH, policy_version)
    state = current_consent(
        db,
        organization_id=request.organization_id,
        contact_id=subject.contact_id,
        channel=subject.channel,
        purpose=subject.purpose,
    )
    if state.effective == EFFECTIVE_GRANTED:
        return None
    if state.effective == EFFECTIVE_REVOKED:
        return _denied(request, REASON_CONSENT_REVOKED, policy_version)
    if state.effective == EFFECTIVE_EXPIRED:
        return _denied(request, REASON_CONSENT_EXPIRED, policy_version)
    return _denied(request, REASON_CONSENT_MISSING, policy_version)


def _reserve_budget(db: Session, request: ExecutionRequest, policy_version: int) -> PolicyDecision | None:
    """Reserve the requested usage. Return a denial when it cannot be reserved, otherwise None."""
    assert request.budget is not None
    try:
        reserve(
            db,
            organization_id=request.organization_id,
            unit=request.budget.unit,
            quantity=request.budget.quantity,
            idempotency_key=request.budget.idempotency_key,
            occurred_at=datetime.now(UTC),
            capability_key=request.capability_key,
            correlation_id=request.correlation_id,
        )
    except BudgetNotConfiguredError:
        return _denied(request, REASON_BUDGET_NOT_CONFIGURED, policy_version)
    except BudgetExceededError:
        return _denied(request, REASON_BUDGET_EXHAUSTED, policy_version)
    except IdempotencyConflictError:
        return _denied(request, REASON_USAGE_KEY_CONFLICT, policy_version)
    return None


def _audit(db: Session, request: ExecutionRequest, decision: PolicyDecision) -> None:
    budget_unit = None
    if request.budget is not None:
        budget_unit = UsageUnit(request.budget.unit).value
    db.add(
        AuditEvent(
            # Each decision carries its own time. Rows written in one transaction would otherwise
            # share the transaction's timestamp, so their order in the trail would be ambiguous.
            occurred_at=datetime.now(UTC),
            user_id=request.actor.user_id if request.actor is not None else None,
            organization_id=request.organization_id,
            event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
            action=EXECUTION_AUDIT_ACTION,
            decision=(AuditDecision.ALLOWED if decision.allowed else AuditDecision.DENIED).value,
            permission_key=request.required_permission,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            correlation_id=request.correlation_id,
            event_metadata=json.dumps(
                {
                    "capability_key": request.capability_key,
                    "reason_code": decision.reason_code,
                    "stage": request.stage,
                    "policy_version": decision.policy_version,
                    "billable": request.billable,
                    "budget_unit": budget_unit,
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()


def authorize_execution(db: Session, request: ExecutionRequest) -> PolicyDecision:
    """Decide whether one execution step may run, and audit the decision."""
    decision = _evaluate(db, request)
    _audit(db, request, decision)
    return decision
