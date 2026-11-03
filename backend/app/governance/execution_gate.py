"""The shared execution gate for AI and customer-impacting automation (WS6 WP4).

Every AI execution entry point and every automation that performs customer-impacting work must call
``evaluate_execution``. It runs the gates in a fixed order and stops at the first failure. Nothing is executed
on a denial. The same function serves synchronous requests and background work, so enforcement is identical.

Gate order (first failure decides):

1. entitlement   SIBVO ``ai_gateway`` snapshot, or the session plan feature for automation. Missing, invalid,
                 expired or revoked entitlement denies. Reuses ``policy.evaluate_capability``.
2. switches      Organization master and capability switches. Reuses ``policy.evaluate_capability``.
3. provider      A configured, verified and usable provider. Fails closed when health is unknown. Reuses
                 ``policy.evaluate_capability``.
4. actor         The authenticated user holds the permission for the capability. A system actor may run only a
                 capability that names a system permission, and none do yet.
5. resource      AI capabilities require a resource. Automation must reference an active rule. There is no AI
                 resource store yet, so AI resources are refused (``resource_not_found``).
6. consent       Capabilities that need consent require a consent record. There is no consent store yet, so
                 these are refused (``consent_not_configured``).
7. approval      Customer-facing capabilities require an approval bound to the exact action payload. There is no
                 approval store yet, so these are refused (``approval_required``).
8. rate          The existing organization and actor rate limits. A type with no approved rule fails closed.
9. budget        Usage is reserved before execution. The reservation is refused when it would exceed the budget,
                 so the limit is a hard stop at 100 percent. The reservation is the last gate, so no release is
                 needed when an earlier gate denies.
10. audit        The decision is recorded in its own transaction (WP3). If that cannot be written, the gate
                 releases any reservation, raises, and nothing executes.

``revalidate_ticket`` re-runs gates 1 to 5 before each later step, so a revoked entitlement, a disabled switch, a
removed permission or a deactivated rule stops the work in flight.

Honest status. Gates 1 to 4, 8, 9, 10 and the in-flight revalidation are implemented. Gates 5 to 7 are
implemented as fail-closed checks against stores that do not exist yet. Therefore no AI capability can pass the
gate today, which is the intended default. Concurrency limits are not implemented, because no limit has been
approved (decision D-6). Serialization for budget and rate counters comes from their row locks.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.attribution import (
    AuditAttribution,
    SystemActorCapability,
    system_attribution,
    user_attribution,
)
from app.audit.independent import (
    OUTCOME_DENIED,
    OUTCOME_REQUESTED,
    AuditPersistenceError,
    persist_independent_audit_event,
)
from app.auth.dependencies import CurrentUserContext
from app.authz.permissions import OWNER_ONLY_PERMISSION_KEYS, OWNER_ROLE_NAME
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.governance.capabilities import (
    AUTOMATION_DEAL_CREATED_RULES,
    CAPABILITY_BY_KEY,
    CapabilityCategory,
)
from app.governance.policy import (
    REASON_ALLOWED,
    REASON_CONSENT_NOT_CONFIGURED,
    REASON_EXECUTION_GATES_PENDING,
    REASON_PROVIDER_NOT_CONNECTED,
    evaluate_capability,
)
from app.governance.usage_ledger import (
    BudgetExceededError,
    BudgetNotConfiguredError,
    UsageUnit,
    release,
    reserve,
    settle,
)
from app.rate_limits.limiter import (
    REASON_RATE_LIMITED,
    RateLimitDecision,
    consume_or_deny,
)
from app.rate_limits.policy import AUTOMATION_DEAL_CREATED_EXECUTION

GATE_ENTITLEMENT = "entitlement"
GATE_SWITCHES = "switches"
GATE_PROVIDER = "provider"
GATE_ACTOR = "actor"
GATE_RESOURCE = "resource"
GATE_CONSENT = "consent"
GATE_APPROVAL = "approval"
GATE_RATE = "rate"
GATE_BUDGET = "budget"
GATE_AUDIT = "audit"

REASON_ALLOWED_ALL = "allowed"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_SYSTEM_ACTOR_NOT_PERMITTED = "system_actor_not_permitted"
REASON_RESOURCE_REQUIRED = "resource_required"
REASON_RESOURCE_NOT_FOUND = "resource_not_found"
REASON_RESOURCE_INACTIVE = "resource_inactive"
REASON_APPROVAL_REQUIRED = "approval_required"
REASON_RATE_NOT_CONFIGURED = "rate_limit_not_configured"
REASON_RATE_LIMITED_GATE = "rate_limited"
REASON_BUDGET_NOT_CONFIGURED = "budget_not_configured"
REASON_BUDGET_EXHAUSTED = "budget_exhausted"
REASON_BUDGET_UNAVAILABLE = "budget_unavailable"
REASON_AUDIT_UNAVAILABLE = "audit_unavailable"
REASON_UNKNOWN_CAPABILITY_GATE = "unknown_capability"

# AI decisions keep the event type the AI entry point has always used. Other capabilities use the gate type.
AI_EXECUTION_EVENT_TYPE = "ai_execution"
EXECUTION_EVENT_TYPE = "execution_gate"

# Capabilities that act on customers or channels. They need an approval bound to the exact payload.
APPROVAL_REQUIRED_CAPABILITIES: frozenset[str] = frozenset({
    "ai.voice",
    "channels.whatsapp",
    "channels.email",
    "channels.sms",
    "channels.voice",
})

# The permission each capability needs. An unlisted AI capability needs ``ai.execute``, which is not in the
# permission catalogue, so no role grants it and it is refused until the permission is defined.
REQUIRED_PERMISSION: dict[str, str] = {
    AUTOMATION_DEAL_CREATED_RULES: "deals.create",
}
DEFAULT_AI_PERMISSION = "ai.execute"
# Rate type for each capability. A capability missing here has no approved rate rule, so it is refused.
RATE_EXECUTION_TYPE: dict[str, str] = {
    AUTOMATION_DEAL_CREATED_RULES: AUTOMATION_DEAL_CREATED_EXECUTION,
}


@dataclass(frozen=True)
class GateOutcome:
    gate: str
    allowed: bool
    reason_code: str


@dataclass(frozen=True)
class ExecutionTicket:
    """Reservations held for one allowed execution. Settle or release them when the work ends."""

    organization_id: UUID
    capability_key: str
    reservation_keys: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (unit, idempotency key)


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    capability_key: str
    reason_code: str
    gate: str | None
    outcomes: tuple[GateOutcome, ...]
    ticket: ExecutionTicket | None = None
    # The limiter's detail when the rate gate ran. Used for the rate-limit record. Never a budget figure.
    rate: RateLimitDecision | None = None


@dataclass(frozen=True)
class ExecutionRequest:
    organization_id: UUID
    capability_key: str
    user_context: CurrentUserContext | None = None
    system_actor: SystemActorCapability | None = None
    resource_id: str | None = None
    budget_units: tuple[tuple[str, int], ...] = ()
    approval_id: UUID | None = None
    approval_payload_hash: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None


def _deny(request: ExecutionRequest, outcomes: list[GateOutcome], gate: str, reason: str) -> ExecutionDecision:
    outcomes.append(GateOutcome(gate=gate, allowed=False, reason_code=reason))
    return ExecutionDecision(
        allowed=False,
        capability_key=request.capability_key,
        reason_code=reason,
        gate=gate,
        outcomes=tuple(outcomes),
    )


def actor_permission_granted(db: Session, *, organization_id: UUID, user_id: UUID, permission_key: str) -> bool:
    """Whether an active membership in the organization grants ``permission_key`` through a role.

    Mirrors ``app.authz.dependencies.permission_granted``, without needing a tenant context object. Owner-only
    keys count only through the system Owner role.
    """
    conditions = [
        Membership.user_id == user_id,
        Membership.organization_id == organization_id,
        Membership.is_active.is_(True),
        Role.organization_id == organization_id,
        Role.is_active.is_(True),
        Permission.key == permission_key,
        Permission.is_active.is_(True),
    ]
    if permission_key in OWNER_ONLY_PERMISSION_KEYS:
        conditions.extend([Role.is_system.is_(True), Role.name == OWNER_ROLE_NAME])
    statement = (
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .join(Membership, Membership.id == MembershipRole.membership_id)
        .where(*conditions)
        .limit(1)
    )
    return db.scalar(statement) is not None


def _attribution(request: ExecutionRequest) -> AuditAttribution:
    """Attribution from the authenticated user, or from a registered system actor. Exactly one."""
    if (request.user_context is None) == (request.system_actor is None):
        raise ValueError("An execution request names exactly one actor: an authenticated user or a system actor.")
    if request.user_context is not None:
        return user_attribution(organization_id=request.organization_id, actor_user_id=request.user_context.user.id)
    return system_attribution(organization_id=request.organization_id, capability=request.system_actor)


def _gate_static(db: Session, request: ExecutionRequest, outcomes: list[GateOutcome]) -> ExecutionDecision | None:
    """Gates 1 to 3, using the existing policy. Returns a denial, or None when they pass."""
    decision = evaluate_capability(
        db,
        organization_id=request.organization_id,
        capability_key=request.capability_key,
        user_context=request.user_context,
        correlation_id=request.correlation_id,
    )
    if decision.reason_code in {REASON_ALLOWED, REASON_EXECUTION_GATES_PENDING}:
        outcomes.append(GateOutcome(gate=GATE_SWITCHES, allowed=True, reason_code=decision.reason_code))
        return None
    gate = {
        REASON_PROVIDER_NOT_CONNECTED: GATE_PROVIDER,
        REASON_CONSENT_NOT_CONFIGURED: GATE_CONSENT,
    }.get(decision.reason_code)
    if gate is None:
        gate = GATE_SWITCHES if decision.reason_code in {"master_disabled", "capability_disabled"} else GATE_ENTITLEMENT
        if decision.reason_code == "unknown_capability":
            gate = GATE_SWITCHES
    return _deny(request, outcomes, gate, decision.reason_code)


def _gate_actor(db: Session, request: ExecutionRequest, outcomes: list[GateOutcome]) -> ExecutionDecision | None:
    if request.system_actor is not None:
        # A system actor needs a system permission. None exists, so every system actor is refused for now.
        return _deny(request, outcomes, GATE_ACTOR, REASON_SYSTEM_ACTOR_NOT_PERMITTED)
    permission = REQUIRED_PERMISSION.get(request.capability_key)
    if permission is None:
        permission = DEFAULT_AI_PERMISSION
    granted = actor_permission_granted(
        db,
        organization_id=request.organization_id,
        user_id=request.user_context.user.id,
        permission_key=permission,
    )
    if not granted:
        return _deny(request, outcomes, GATE_ACTOR, REASON_PERMISSION_DENIED)
    outcomes.append(GateOutcome(gate=GATE_ACTOR, allowed=True, reason_code=REASON_ALLOWED_ALL))
    return None


def _gate_resource(db: Session, request: ExecutionRequest, outcomes: list[GateOutcome]) -> ExecutionDecision | None:
    definition = CAPABILITY_BY_KEY[request.capability_key]
    if definition.category is CapabilityCategory.AI:
        if request.resource_id is None:
            return _deny(request, outcomes, GATE_RESOURCE, REASON_RESOURCE_REQUIRED)
        # No AI resource store exists yet, so no AI resource can be proven configured and published.
        return _deny(request, outcomes, GATE_RESOURCE, REASON_RESOURCE_NOT_FOUND)
    if request.capability_key == AUTOMATION_DEAL_CREATED_RULES:
        # Rules are checked one by one as they run, so a capability-level request needs no rule reference.
        outcomes.append(GateOutcome(gate=GATE_RESOURCE, allowed=True, reason_code=REASON_ALLOWED_ALL))
        return None
    outcomes.append(GateOutcome(gate=GATE_RESOURCE, allowed=True, reason_code=REASON_ALLOWED_ALL))
    return None


def _gate_consent(request: ExecutionRequest, outcomes: list[GateOutcome]) -> ExecutionDecision | None:
    definition = CAPABILITY_BY_KEY[request.capability_key]
    if definition.requires_consent:
        # No consent store exists yet, so consent cannot be proven, including after a revocation.
        return _deny(request, outcomes, GATE_CONSENT, REASON_CONSENT_NOT_CONFIGURED)
    outcomes.append(GateOutcome(gate=GATE_CONSENT, allowed=True, reason_code=REASON_ALLOWED_ALL))
    return None


def _gate_approval(request: ExecutionRequest, outcomes: list[GateOutcome]) -> ExecutionDecision | None:
    if request.capability_key not in APPROVAL_REQUIRED_CAPABILITIES:
        outcomes.append(GateOutcome(gate=GATE_APPROVAL, allowed=True, reason_code="not_required"))
        return None
    # No approval store exists yet. Approval can only be proven by a record bound to this payload hash.
    return _deny(request, outcomes, GATE_APPROVAL, REASON_APPROVAL_REQUIRED)


def _gate_rate(db: Session, request: ExecutionRequest, outcomes: list[GateOutcome]) -> ExecutionDecision | None:
    execution_type = RATE_EXECUTION_TYPE.get(request.capability_key)
    if execution_type is None:
        return _deny(request, outcomes, GATE_RATE, REASON_RATE_NOT_CONFIGURED)
    actor = request.user_context.user.id if request.user_context is not None else None
    rate = consume_or_deny(
        db,
        organization_id=request.organization_id,
        execution_type=execution_type,
        actor_user_id=actor,
    )
    if not rate.allowed:
        reason = REASON_RATE_LIMITED_GATE if rate.reason_code == REASON_RATE_LIMITED else rate.reason_code
        denial = _deny(request, outcomes, GATE_RATE, reason)
        return replace(denial, rate=rate)
    outcomes.append(GateOutcome(gate=GATE_RATE, allowed=True, reason_code=REASON_ALLOWED_ALL))
    return None


def _reserve_budget(
    db: Session, request: ExecutionRequest, outcomes: list[GateOutcome], now: datetime
) -> tuple[ExecutionDecision | None, tuple[tuple[str, str], ...]]:
    reservations: list[tuple[str, str]] = []
    base_key = request.idempotency_key or f"gate:{request.correlation_id or 'none'}:{request.capability_key}"
    try:
        for unit, quantity in request.budget_units:
            key = f"{base_key}:{unit}"
            reserve(
                db,
                organization_id=request.organization_id,
                unit=UsageUnit(unit),
                quantity=quantity,
                idempotency_key=key,
                occurred_at=now,
                user_id=request.user_context.user.id if request.user_context is not None else None,
                correlation_id=request.correlation_id,
            )
            reservations.append((unit, key))
    except BudgetNotConfiguredError:
        _release_all(db, request.organization_id, reservations)
        return _deny(request, outcomes, GATE_BUDGET, REASON_BUDGET_NOT_CONFIGURED), ()
    except BudgetExceededError:
        _release_all(db, request.organization_id, reservations)
        return _deny(request, outcomes, GATE_BUDGET, REASON_BUDGET_EXHAUSTED), ()
    outcomes.append(GateOutcome(gate=GATE_BUDGET, allowed=True, reason_code=REASON_ALLOWED_ALL))
    return None, tuple(reservations)


def _release_all(db: Session, organization_id: UUID, reservations: list[tuple[str, str]] | tuple) -> None:
    for _unit, key in reservations:
        release(db, organization_id=organization_id, idempotency_key=key)


def _record(
    db: Session,
    request: ExecutionRequest,
    attribution: AuditAttribution,
    decision: ExecutionDecision,
) -> None:
    """Record the decision in its own transaction. Raises ``AuditPersistenceError`` when it cannot be written."""
    persist_independent_audit_event(
        db,
        attribution=attribution,
        event_type=(
            AI_EXECUTION_EVENT_TYPE
            if CAPABILITY_BY_KEY[request.capability_key].category is CapabilityCategory.AI
            else EXECUTION_EVENT_TYPE
        ),
        action="allowed" if decision.allowed else "denied",
        decision="allowed" if decision.allowed else "denied",
        outcome=OUTCOME_REQUESTED if decision.allowed else OUTCOME_DENIED,
        permission_key=f"capability:{request.capability_key}",
        resource_type="capability",
        resource_id=request.capability_key,
        correlation_id=request.correlation_id,
        idempotency_key=request.idempotency_key,
        metadata={
            "reason_code": decision.reason_code,
            "gate": decision.gate,
            "gates": [{"gate": item.gate, "allowed": item.allowed, "reason": item.reason_code}
                      for item in decision.outcomes],
        },
    )


def evaluate_execution(db: Session, request: ExecutionRequest, *, now: datetime | None = None) -> ExecutionDecision:
    """Run every gate in order and record the decision. Nothing may execute unless ``allowed`` is True.

    Raises ``AuditAttributionError`` when the actor cannot be attributed, and ``AuditPersistenceError`` when the
    decision cannot be recorded. In both cases the caller must not execute.
    """
    if request.capability_key not in CAPABILITY_BY_KEY:
        raise ValueError("Unknown capability.")
    attribution = _attribution(request)
    moment = now or datetime.now(UTC)
    outcomes: list[GateOutcome] = []

    decision = _gate_static(db, request, outcomes)
    if decision is None:
        decision = _gate_actor(db, request, outcomes)
    if decision is None:
        decision = _gate_resource(db, request, outcomes)
    if decision is None:
        decision = _gate_consent(request, outcomes)
    if decision is None:
        decision = _gate_approval(request, outcomes)
    if decision is None:
        decision = _gate_rate(db, request, outcomes)

    reservations: tuple[tuple[str, str], ...] = ()
    if decision is None:
        decision, reservations = _reserve_budget(db, request, outcomes, moment)

    if decision is None:
        decision = ExecutionDecision(
            allowed=True,
            capability_key=request.capability_key,
            reason_code=REASON_ALLOWED_ALL,
            gate=None,
            outcomes=tuple(outcomes),
            ticket=ExecutionTicket(
                organization_id=request.organization_id,
                capability_key=request.capability_key,
                reservation_keys=reservations,
            ),
        )

    try:
        _record(db, request, attribution, decision)
    except AuditPersistenceError:
        _release_all(db, request.organization_id, reservations)
        raise
    return decision


def settle_ticket(db: Session, ticket: ExecutionTicket, actual: dict[str, int]) -> None:
    """Settle each reservation with its actual usage. Units not in ``actual`` are released."""
    for unit, key in ticket.reservation_keys:
        if unit in actual:
            settle(db, organization_id=ticket.organization_id, idempotency_key=key, actual_quantity=actual[unit])
        else:
            release(db, organization_id=ticket.organization_id, idempotency_key=key)


def release_ticket(db: Session, ticket: ExecutionTicket) -> None:
    """Release every reservation held by an execution that failed or was cancelled."""
    _release_all(db, ticket.organization_id, ticket.reservation_keys)


def revalidate_ticket(db: Session, request: ExecutionRequest) -> ExecutionDecision:
    """Re-check the governing gates before a later step. Denies when any of them no longer holds.

    This does not reserve, record or consume anything. It answers whether the next step may run.
    """
    outcomes: list[GateOutcome] = []
    decision = _gate_static(db, request, outcomes)
    if decision is None:
        decision = _gate_actor(db, request, outcomes)
    if decision is None:
        decision = _gate_resource(db, request, outcomes)
    if decision is None:
        return ExecutionDecision(
            allowed=True,
            capability_key=request.capability_key,
            reason_code=REASON_ALLOWED_ALL,
            gate=None,
            outcomes=tuple(outcomes),
        )
    return decision
