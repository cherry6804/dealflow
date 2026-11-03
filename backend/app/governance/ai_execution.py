"""The single entry point for AI execution, synchronous or background (WS5, ADR-0029, WS6 WP4).

Every AI execution path must call ``require_ai_execution`` before any provider call or billable work. It runs
the shared execution gate (``app.governance.execution_gate``), so the order and the checks are the same for
requests and for background work. A denial is recorded independently and raised. A denial is never silently
swallowed, and nothing executes unless every gate passes.

No AI capability can pass the gate today. Resource, consent and approval stores do not exist yet, so each of
those gates refuses. This is the intended default, and it is not a claim that AI execution is available.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.attribution import register_system_actor
from app.auth.dependencies import CurrentUserContext
from app.governance.execution_gate import (
    ExecutionDecision,
    ExecutionRequest,
    evaluate_execution,
)

# The AI execution gate's own system actor. Only this module holds its capability (WP3 hardening).
_AI_GATE_ACTOR = register_system_actor("ai_execution_gate")


class AiExecutionDenied(Exception):
    """AI execution is not allowed. ``decision`` carries the stable reason code and the gate that refused."""

    def __init__(self, decision: ExecutionDecision) -> None:
        super().__init__(decision.reason_code)
        self.decision = decision


def require_ai_execution(
    db: Session,
    *,
    organization_id: UUID,
    capability_key: str,
    user_context: CurrentUserContext | None = None,
    correlation_id: str | None = None,
    resource_id: str | None = None,
    budget_units: tuple[tuple[str, int], ...] = (),
    approval_id: UUID | None = None,
    approval_payload_hash: str | None = None,
    idempotency_key: str | None = None,
) -> ExecutionDecision:
    """Return the decision when every gate passes. Otherwise record the denial and raise ``AiExecutionDenied``.

    The caller does not need to commit the denial record. It is committed in its own transaction (WP3). If it
    cannot be written, ``AuditPersistenceError`` is raised instead, and execution still does not proceed.
    """
    request = ExecutionRequest(
        organization_id=organization_id,
        capability_key=capability_key,
        user_context=user_context,
        system_actor=None if user_context is not None else _AI_GATE_ACTOR,
        resource_id=resource_id,
        budget_units=budget_units,
        approval_id=approval_id,
        approval_payload_hash=approval_payload_hash,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    decision = evaluate_execution(db, request)
    if not decision.allowed:
        raise AiExecutionDenied(decision)
    return decision
