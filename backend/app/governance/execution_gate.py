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
    )
    if not policy.allowed:
        return policy

    if request.required_permission is not None:
        organization = db.get(Organization, request.organization_id)
        if organization is None:
            return _denied(request, REASON_WRONG_ORGANIZATION)
        tenant = TenantContext(organization=organization, membership=membership)
        if not permission_granted(
            db, tenant_context=tenant, permission_key=request.required_permission
        ):
            return _denied(request, REASON_ACTOR_NOT_AUTHORIZED, policy.policy_version)

    if request.billable:
        # Budget is reserved last, after every other check, so a refused execution never holds usage.
        if request.budget is None:
            return _denied(request, REASON_BUDGET_RESERVATION_REQUIRED, policy.policy_version)
        reservation_refusal = _reserve_budget(db, request, policy.policy_version)
        if reservation_refusal is not None:
            return reservation_refusal

    return PolicyDecision(
        capability_key=request.capability_key,
        organization_id=request.organization_id,
        allowed=True,
        reason_code=REASON_ALLOWED,
        explanation=_EXPLANATIONS[REASON_ALLOWED],
        policy_version=policy.policy_version,
        correlation_id=request.correlation_id,
    )


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
