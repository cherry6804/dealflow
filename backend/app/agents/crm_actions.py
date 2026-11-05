"""Handlers for the CRM actions an agent plan may name (DFR1-021).

Every action runs as the execution's initiating member. Its permissions are checked here, before the handler runs, and the
services it calls check them again. A refused permission stops the execution at that step, with a reason. A service error rolls
back only the action's own work (a savepoint) and fails the step with the service's reason code.

Agents write through these services only: the intake service (contacts and leads), the DFR1-020 priority service, and the
qualification service. No action writes a lead's own fields, so an agent cannot overwrite a human's change to a lead.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.crm_action_catalogue import (
    CRM_ACTIONS,
    INTAKE_PROCESS,
    INTAKE_RESOLVE_IDENTITY,
    LEAD_CALCULATE_PRIORITY,
    MATCHING_EVALUATE,
    QUALIFICATION_RECORD,
)
from app.db.models.agent import AgentExecution
from app.governance.execution_gate import actor_permission_granted
from app.leads.intake import decide_match
from app.leads.intake_service import (
    IntakeError,
    get_submission,
    identity_candidates,
    process_submission,
)
from app.leads.priority_service import PriorityError, calculate_and_store
from app.leads.qualification import QualificationError, record_qualification
from app.requirements.match_evaluation_service import (
    EvaluationError,
    evaluate_requirement,
)

REASON_UNKNOWN_ACTION = "unknown_crm_action"
REASON_PERMISSION_DENIED = "crm_permission_denied"
REASON_INVALID_ARGUMENT = "invalid_crm_argument"
REASON_FAILED = "crm_action_failed"

CRM_ACTION_OK = "succeeded"


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _intake_process(db: Session, execution: AgentExecution, arguments: dict[str, Any]) -> dict[str, Any]:
    submission = process_submission(db, organization_id=execution.organization_id, actor_id=execution.initiated_by_user_id,
                                    submission_id=arguments["submission_id"])
    return {
        "submission_id": str(submission.id),
        "status": submission.status,
        "match_outcome": submission.match_outcome,
        "lead_id": str(submission.lead_id) if submission.lead_id else None,
    }


def _intake_resolve_identity(db: Session, execution: AgentExecution, arguments: dict[str, Any]) -> dict[str, Any]:
    # Read only: the outcome is computed and returned, and nothing is stored or written to the CRM.
    submission = get_submission(db, organization_id=execution.organization_id, submission_id=arguments["submission_id"])
    if submission.normalized_payload is None:
        raise IntakeError("invalid_submission")
    candidates = identity_candidates(db, organization_id=execution.organization_id, normalized=submission.normalized_payload)
    return {"submission_id": str(submission.id), "outcome": decide_match(submission.normalized_payload, candidates),
            "candidate_count": len(candidates)}


def _lead_calculate_priority(db: Session, execution: AgentExecution, arguments: dict[str, Any]) -> dict[str, Any]:
    row = calculate_and_store(db, organization_id=execution.organization_id, actor_id=execution.initiated_by_user_id,
                              lead_id=arguments["lead_id"])
    return {
        "score_id": str(row.id),
        "score": row.score,
        "band": row.band,
        "method": row.method,
        "confidence": row.confidence,
        "insufficient_data": row.insufficient_data,
        "ruleset_version": row.ruleset_version,
    }


def _qualification_record(db: Session, execution: AgentExecution, arguments: dict[str, Any]) -> dict[str, Any]:
    suggestion = arguments.get("suggestion")
    row, created = record_qualification(
        db,
        organization_id=execution.organization_id,
        actor_id=execution.initiated_by_user_id,
        execution_id=execution.id,
        lead_id=arguments["lead_id"],
        score_id=arguments["score_id"],
        suggestion=suggestion if isinstance(suggestion, str) else None,
    )
    return {"qualification_id": str(row.id), "requires_review": row.requires_review, "created": created}


def _matching_evaluate(db: Session, execution: AgentExecution, arguments: dict[str, Any]) -> dict[str, Any]:
    run, created = evaluate_requirement(db, organization_id=execution.organization_id,
                                        actor_id=execution.initiated_by_user_id, requirement_id=arguments["requirement_id"])
    return {"run_id": str(run.id), "created": created, "ruleset_version": run.ruleset_version}


_HANDLERS = {
    MATCHING_EVALUATE: _matching_evaluate,
    INTAKE_PROCESS: _intake_process,
    INTAKE_RESOLVE_IDENTITY: _intake_resolve_identity,
    LEAD_CALCULATE_PRIORITY: _lead_calculate_priority,
    QUALIFICATION_RECORD: _qualification_record,
}

_UUID_ARGUMENTS = frozenset({"submission_id", "lead_id", "score_id", "requirement_id"})


def run_crm_action(db: Session, execution: AgentExecution, action_key: str,
                   arguments: dict[str, Any]) -> tuple[str, str | None, dict[str, object] | None]:
    """Run one CRM action. Returns ``(status, reason, trace)`` in the runtime's step vocabulary."""
    spec = CRM_ACTIONS.get(action_key)
    handler = _HANDLERS.get(action_key)
    if spec is None or handler is None:
        return "failed", REASON_UNKNOWN_ACTION, None
    for permission in spec.permissions:
        if not actor_permission_granted(db, organization_id=execution.organization_id,
                                        user_id=execution.initiated_by_user_id, permission_key=permission):
            return "stopped", REASON_PERMISSION_DENIED, None

    typed: dict[str, Any] = {}
    for name, value in arguments.items():
        if name in _UUID_ARGUMENTS:
            parsed = _uuid(value)
            if parsed is None:
                return "failed", REASON_INVALID_ARGUMENT, None
            typed[name] = parsed
        else:
            typed[name] = value
    if any(name not in typed or typed[name] is None for name in spec.required_arguments):
        return "failed", REASON_INVALID_ARGUMENT, None

    try:
        with db.begin_nested():
            output = handler(db, execution, typed)
    except (IntakeError, PriorityError, QualificationError, EvaluationError) as error:
        if error.reason == "permission_denied":
            return "stopped", REASON_PERMISSION_DENIED, None
        return "failed", error.reason, None
    return CRM_ACTION_OK, None, {"output": output, "action": action_key}
