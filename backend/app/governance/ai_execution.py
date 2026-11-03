"""The single gate for AI execution, synchronous or background (WS5, ADR-0029).

Every AI execution path must call ``require_ai_execution`` before any provider call or billable work.
It uses the same policy as the capability listing. A denial is audited and raised. There is no
bypass for background callers: they reach SIBVO through the authenticated organization snapshot.

Today the policy ends in ``execution_gates_pending`` even when every available gate passes, because
consent, budget, approval and resource activation are not built. So this function never allows
execution yet. That is deliberate.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.independent import OUTCOME_DENIED, persist_independent_audit_event
from app.auth.dependencies import CurrentUserContext
from app.governance.policy import PolicyDecision, evaluate_capability

AI_EXECUTION_EVENT_TYPE = "ai_execution"


class AiExecutionDenied(Exception):
    """AI execution is not allowed. ``decision`` carries the stable reason code."""

    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__(decision.reason_code)
        self.decision = decision


def require_ai_execution(
    db: Session,
    *,
    organization_id: UUID,
    capability_key: str,
    user_context: CurrentUserContext | None = None,
    correlation_id: str | None = None,
) -> PolicyDecision:
    """Return the decision when allowed, otherwise record the denial and raise ``AiExecutionDenied``.

    The denial is committed in its own transaction (WP3), so it survives the caller rolling back, and the
    caller does not need to commit it. If it cannot be written, ``AuditPersistenceError`` is raised instead
    of the denial. Either way, execution does not proceed.
    """
    decision = evaluate_capability(
        db,
        organization_id=organization_id,
        capability_key=capability_key,
        user_context=user_context,
        correlation_id=correlation_id,
    )
    if decision.allowed:
        return decision

    persist_independent_audit_event(
        db,
        organization_id=organization_id,
        actor_user_id=user_context.user.id if user_context is not None else None,
        event_type=AI_EXECUTION_EVENT_TYPE,
        action="denied",
        decision="denied",
        outcome=OUTCOME_DENIED,
        permission_key=f"capability:{capability_key}",
        resource_type="capability",
        resource_id=capability_key,
        correlation_id=correlation_id,
        metadata={"reason_code": decision.reason_code},
    )
    raise AiExecutionDenied(decision)
