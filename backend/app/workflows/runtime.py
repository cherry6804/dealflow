"""Durable, bounded execution of published workflow versions (DFR1-024).

A run starts from a manual request or from a declared event, and is bound to one immutable version. Starting it checks the
organization's state (automation capability and entitlement, the run-as member, the version's actions and agents, the workflow's
status, concurrency and hourly limits) and queues an outbox event. The worker then runs the steps in order. Every boundary checks the
state again, so a paused or archived workflow, a switched-off automation capability, a revoked membership or a lost permission stops
the run at that boundary with a reason. No step runs after a failed check.

Step handlers reuse existing components and add no authorization of their own:

- crm_action: the CRM action runner shared with agents (``app/agents/crm_actions.py``), as the run-as member;
- condition: a fixed comparison on a reference and a literal, branching to ``then`` or ``else``;
- agent: the agent runtime (``create_execution`` and ``run_execution``), as the run-as member, with its own limits and gates;
- approval: the run waits until a member with the step's approver permission decides, not the run-as member;
- delay: the run waits until a durable wake time, then a timer sweep resumes it.

Limits: duration, step count, retry attempts, concurrency per workflow, runs per hour per workflow, and output size. A transient
failure is retried a bounded number of times and then dead-lettered. A permanent failure fails the run. Nothing is retried without a
limit. Cancellation and timeouts are honoured at the next boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.agents.crm_actions import (
    REASON_PERMISSION_DENIED as CRM_REASON_PERMISSION_DENIED,
)
from app.agents.crm_actions import run_crm_action
from app.agents.runtime import create_execution as create_agent_execution
from app.agents.runtime import run_execution as run_agent_execution
from app.agents.service import AgentError
from app.audit.attribution import (
    register_system_actor,
    system_attribution,
    user_attribution,
)
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.auth.dependencies import CurrentUserContext
from app.db.models.agent import AgentExecution
from app.db.models.approval_request import ApprovalRequest
from app.db.models.human_task import HumanTask
from app.db.models.membership import Membership
from app.db.models.user import User
from app.db.models.workflow import WorkflowDefinition, WorkflowVersion
from app.db.models.workflow_execution import WorkflowExecution, WorkflowExecutionStep
from app.governance.approvals import (
    ApprovalError,
    check_approval_for_execution,
    consume_approval,
    payload_hash,
)
from app.governance.capabilities import AUTOMATION_WORKFLOWS
from app.governance.execution_gate import actor_permission_granted
from app.governance.policy import evaluate_capability
from app.human_tasks import service as human_tasks
from app.outbox.service import enqueue_event
from app.workflows.publish_checks import publish_problems
from app.workflows.schema import DEFAULT_APPROVAL_EXPIRY_SECONDS, MAX_DELAY_SECONDS

WORKFLOW_SYSTEM_ACTOR = register_system_actor("workflow_runtime")
EXECUTION_REQUESTED_EVENT = "workflow.execution_requested"
EXECUTION_AUDIT_EVENT = "workflow_execution"
PERMISSION_RUN = "workflows.run"
PERMISSION_READ = "workflows.read"

MAX_TRACE_CHARACTERS = 2_000
MAX_OUTPUT_CHARACTERS = 16_384
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5
MAX_IDEMPOTENCY_KEY = 200
ACTIVE_LOOKBACK = timedelta(hours=1)
DUE_TIMER_BATCH = 100

REASON_PERMISSION_DENIED = "permission_denied"
REASON_NOT_FOUND = "execution_not_found"
REASON_WORKFLOW_NOT_FOUND = "workflow_not_found"
REASON_NOT_RUNNABLE = "workflow_not_runnable"
REASON_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
REASON_CONCURRENCY = "concurrency_limit"
REASON_RATE_LIMITED = "rate_limited"
REASON_INVALID_INPUT = "invalid_input"
REASON_NO_VERSION = "no_published_version"
REASON_NOT_WAITING = "not_waiting_for_approval"
REASON_SELF_APPROVAL = "self_approval_refused"
REASON_NOT_CANCELLABLE = "already_finished"
REASON_NOT_RETRYABLE = "not_retryable"
REASON_STEP_NOT_FOUND = "step_not_found"
REASON_AUTOMATION_DISABLED = "automation_disabled"
REASON_WORKFLOW_PAUSED = "workflow_paused"
REASON_WORKFLOW_ARCHIVED = "workflow_archived"
REASON_MEMBERSHIP_REVOKED = "membership_revoked"
REASON_DEADLINE = "deadline_exceeded"
REASON_CANCEL = "cancel_requested"
REASON_STEP_LIMIT = "step_limit"
REASON_INTERRUPTED = "interrupted_step"
REASON_TRANSIENT_EXHAUSTED = "transient_failure_exhausted"
REASON_OUTPUT_TOO_LARGE = "output_too_large"
REASON_APPROVAL_REJECTED = "approval_rejected"
REASON_AGENT_WAITING = "agent_waiting_approval"
REASON_BAD_REFERENCE = "unresolved_reference"

_STEP_FIELD = re.compile(r"^\$steps\.([a-z][a-z0-9_]{0,39})\.([a-z][a-z0-9_]{0,39})$")
_INPUT = re.compile(r"^\$input\.([a-z][a-z0-9_]{0,39})$")
ACTIVE_STATUSES = WorkflowExecution.ACTIVE_STATUSES

Sleep = Callable[[float], None]
BoundaryHook = Callable[[Session, WorkflowExecution], None]


class ExecutionError(Exception):
    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


@dataclass(frozen=True)
class WorkflowCaller:
    """The CRM caller for a workflow step: the run-as member, and no agent execution."""

    organization_id: UUID
    initiated_by_user_id: UUID
    id: UUID | None = None


# --- helpers -----------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _bounded(value: object, limit: int) -> dict[str, Any] | None:
    encoded = json.dumps(value, sort_keys=True, default=str)
    if len(encoded) > limit:
        return None
    return json.loads(encoded)


def _membership_active(db: Session, *, organization_id: UUID, user_id: UUID) -> bool:
    return db.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id,
        Membership.user_id == user_id,
        Membership.is_active.is_(True),
    )) is not None


def _audit(db: Session, execution: WorkflowExecution, action: str, metadata: dict[str, Any],
           actor_id: UUID | None = None) -> None:
    """Record a lifecycle change. The acting member is the one who made it (a decider or a canceller), else the run-as member."""
    actor = actor_id or execution.run_as_user_id
    if actor_id is None and not _membership_active(db, organization_id=execution.organization_id, user_id=actor):
        # The run-as member no longer belongs to the organization, so the worker records the change under the system actor.
        attribution = system_attribution(organization_id=execution.organization_id, capability=WORKFLOW_SYSTEM_ACTOR)
    else:
        attribution = user_attribution(organization_id=execution.organization_id, actor_user_id=actor)
    persist_independent_audit_event(
        db,
        attribution=attribution,
        event_type=EXECUTION_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key=PERMISSION_RUN,
        resource_type="workflow_execution",
        resource_id=str(execution.id),
        correlation_id=execution.correlation_id,
        metadata=dict(metadata, status=execution.status, version_number=execution.version_number,
                      workflow_id=str(execution.workflow_id)),
    )


def resolve(value: Any, inputs: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> Any:
    """A ``$input.name`` or ``$steps.id.field`` reference becomes its value. Anything else is refused by the caller."""
    if isinstance(value, str):
        match = _INPUT.fullmatch(value)
        if match is not None:
            return inputs.get(match.group(1))
        step_match = _STEP_FIELD.fullmatch(value)
        if step_match is not None:
            output = outputs.get(step_match.group(1)) or {}
            return output.get(step_match.group(2))
    return value


def compare(left: Any, operator: str, right: Any) -> bool:
    """A fixed comparison. Nothing here evaluates text as code."""
    if operator == "exists":
        return left is not None and left != ""
    if operator == "eq":
        return left == right or (left is not None and str(left) == str(right))
    if operator == "neq":
        return not compare(left, "eq", right)
    if operator == "in":
        return left is not None and str(left) in [str(item) for item in (right or [])]
    if operator == "not_in":
        return not compare(left, "in", right)
    if left is None or right is None:
        return False
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return False
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}.get(operator, False)


def validate_inputs(declared: list[dict[str, Any]], values: object) -> dict[str, Any]:
    """Check run input against the version's declared inputs. Raises ``ExecutionError``."""
    if not isinstance(values, dict):
        raise ExecutionError(REASON_INVALID_INPUT, ["The input must be an object."], status=422)
    by_name = {item["name"]: item for item in declared}
    problems: list[str] = []
    for name in values:
        if name not in by_name:
            problems.append("The input has an undeclared field.")
    typed: dict[str, Any] = {}
    for name, spec in by_name.items():
        if name not in values:
            if spec["required"]:
                problems.append(f"Input {name} is required.")
            continue
        value = values[name]
        if spec["type"] == "uuid":
            try:
                typed[name] = str(UUID(str(value)))
            except (TypeError, ValueError):
                problems.append(f"Input {name} must be an identifier.")
        elif spec["type"] == "integer":
            if isinstance(value, int) and not isinstance(value, bool):
                typed[name] = value
            else:
                problems.append(f"Input {name} must be an integer.")
        elif spec["type"] == "boolean":
            if isinstance(value, bool):
                typed[name] = value
            else:
                problems.append(f"Input {name} must be true or false.")
        else:
            if isinstance(value, str) and 0 < len(value) <= 200:
                typed[name] = value
            else:
                problems.append(f"Input {name} must be short text.")
    if problems:
        raise ExecutionError(REASON_INVALID_INPUT, problems, status=422)
    return typed


def _limits(configuration: dict[str, Any]) -> dict[str, int]:
    return configuration["limits"]


def _start_problems(db: Session, *, organization_id: UUID, workflow: WorkflowDefinition, version: WorkflowVersion,
                    run_as_user_id: UUID, user_context: CurrentUserContext | None) -> list[str]:
    """Everything that must hold before a run may start. Empty when it may. Fails closed."""
    problems: list[str] = []
    if workflow.status != WorkflowDefinition.STATUS_PUBLISHED:
        problems.append(f"The workflow is {workflow.status} and cannot start new runs.")
    if not _membership_active(db, organization_id=organization_id, user_id=run_as_user_id):
        problems.append("The member the run would act as is not active in this organization.")
    decision = evaluate_capability(db, organization_id=organization_id, capability_key=AUTOMATION_WORKFLOWS,
                                   user_context=user_context)
    if not decision.allowed:
        problems.append(f"Workflow automation is not available now: {decision.reason_code}.")
    problems.extend(item["message"] for item in publish_problems(
        db, organization_id=organization_id, actor_id=run_as_user_id, configuration=version.configuration,
        user_context=user_context))
    return problems


def _concurrency_problems(db: Session, *, organization_id: UUID, workflow_id: UUID, limits: dict[str, int]) -> str | None:
    active = db.scalar(select(func.count()).select_from(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id,
        WorkflowExecution.workflow_id == workflow_id,
        WorkflowExecution.status.in_(ACTIVE_STATUSES),
    )) or 0
    if active >= limits["max_concurrent_runs"]:
        return REASON_CONCURRENCY
    since = _now() - ACTIVE_LOOKBACK
    recent = db.scalar(select(func.count()).select_from(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id,
        WorkflowExecution.workflow_id == workflow_id,
        WorkflowExecution.created_at >= since,
    )) or 0
    if recent >= limits["max_runs_per_hour"]:
        return REASON_RATE_LIMITED
    return None


def _enqueue(db: Session, execution: WorkflowExecution, *, token: str | None = None) -> None:
    """Queue the run for the worker. A start uses a fixed key. A resume passes a fresh token, so a resume after a wait is
    delivered even though the start was already delivered under the first key."""
    key = f"workflow-execution:{execution.id}" if token is None else f"workflow-execution:{execution.id}:{token}"
    enqueue_event(
        db,
        organization_id=execution.organization_id,
        event_type=EXECUTION_REQUESTED_EVENT,
        aggregate_type="workflow_execution",
        aggregate_id=str(execution.id),
        idempotency_key=key,
        payload={"execution_id": str(execution.id), "user_id": str(execution.run_as_user_id)},
        correlation_id=execution.correlation_id,
    )


def _create(db: Session, *, organization_id: UUID, workflow: WorkflowDefinition, version: WorkflowVersion,
            run_as_user_id: UUID, initiated_by: UUID | None, trigger_type: str, trigger_event: str | None,
            event_key: str | None, source_execution_id: UUID | None, retry_of: UUID | None,
            idempotency_key: str, inputs: dict[str, Any]) -> WorkflowExecution:
    execution = WorkflowExecution(
        organization_id=organization_id,
        workflow_id=workflow.id,
        version_id=version.id,
        version_number=version.version_number,
        status=WorkflowExecution.STATUS_QUEUED,
        trigger_type=trigger_type,
        trigger_event=trigger_event,
        event_key=event_key,
        source_execution_id=source_execution_id,
        retry_of_execution_id=retry_of,
        idempotency_key=idempotency_key,
        input_hash=_hash({"workflow": str(workflow.id), "version": str(version.id), "input": inputs}),
        input_values=inputs,
        run_as_user_id=run_as_user_id,
        initiated_by_user_id=initiated_by,
        correlation_id=str(uuid.uuid4()),
        steps_completed=0,
    )
    db.add(execution)
    db.flush()
    _audit(db, execution, "workflow.execution.queued", {"trigger_type": trigger_type, "trigger_event": trigger_event})
    _enqueue(db, execution)
    return execution


def _current_version(db: Session, workflow: WorkflowDefinition) -> WorkflowVersion | None:
    if workflow.current_version_id is None:
        return None
    return db.get(WorkflowVersion, workflow.current_version_id)


def _lock_workflow(db: Session, *, organization_id: UUID, workflow_id: UUID) -> WorkflowDefinition:
    workflow = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.id == workflow_id,
        WorkflowDefinition.organization_id == organization_id,
    ).with_for_update())
    if workflow is None:
        raise ExecutionError(REASON_WORKFLOW_NOT_FOUND, status=404)
    return workflow


def start_manual(db: Session, *, organization_id: UUID, user_context: CurrentUserContext, workflow_id: UUID,
                 input_values: object, idempotency_key: str) -> tuple[WorkflowExecution, bool]:
    """Start a run for the signed-in member. Returns ``(execution, created)``. A repeated key with the same input returns the stored run."""
    actor = user_context.user.id
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor, permission_key=PERMISSION_RUN):
        raise ExecutionError(REASON_PERMISSION_DENIED, status=403)
    key = idempotency_key.strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY:
        raise ExecutionError("invalid_idempotency_key", ["The idempotency key must be 1 to 200 characters."], status=422)
    workflow = _lock_workflow(db, organization_id=organization_id, workflow_id=workflow_id)
    version = _current_version(db, workflow)
    typed = validate_inputs(version.configuration.get("inputs", []), input_values) if version else {}
    scoped_key = f"manual:{key}"
    existing = db.scalar(select(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id,
        WorkflowExecution.idempotency_key == scoped_key,
    ))
    if existing is not None:
        if existing.workflow_id == workflow.id and existing.input_hash == _hash(
                {"workflow": str(workflow.id), "version": str(existing.version_id), "input": typed}):
            return existing, False
        raise ExecutionError(REASON_IDEMPOTENCY_CONFLICT, ["This idempotency key was used for a different request."])
    if version is None:
        raise ExecutionError(REASON_NO_VERSION, ["Publish the workflow before starting a run."])
    problems = _start_problems(db, organization_id=organization_id, workflow=workflow, version=version,
                               run_as_user_id=actor, user_context=user_context)
    if problems:
        raise ExecutionError(REASON_NOT_RUNNABLE, problems)
    blocked = _concurrency_problems(db, organization_id=organization_id, workflow_id=workflow.id,
                                    limits=_limits(version.configuration))
    if blocked:
        raise ExecutionError(blocked, ["The workflow has reached its concurrency or hourly run limit."], status=429)
    execution = _create(db, organization_id=organization_id, workflow=workflow, version=version, run_as_user_id=actor,
                        initiated_by=actor, trigger_type="manual", trigger_event=None, event_key=None,
                        source_execution_id=None, retry_of=None, idempotency_key=scoped_key, inputs=typed)
    return execution, True


def start_for_event(db: Session, *, organization_id: UUID, workflow: WorkflowDefinition, version: WorkflowVersion,
                    event_type: str, event_key: str, data: dict[str, Any]) -> WorkflowExecution | None:
    """Start the run for one declared event. Returns None when the run is skipped (the reason is audited, not retried)."""
    scoped_key = f"event:{event_type}:{event_key}:{workflow.id}"
    existing = db.scalar(select(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id,
        WorkflowExecution.idempotency_key == scoped_key,
    ))
    if existing is not None:
        return None
    run_as = version.published_by_user_id
    problems = _start_problems(db, organization_id=organization_id, workflow=workflow, version=version,
                               run_as_user_id=run_as, user_context=None)
    inputs: dict[str, Any] = {}
    for spec in version.configuration.get("inputs", []):
        if spec["name"] in data:
            inputs[spec["name"]] = data[spec["name"]]
    try:
        typed = validate_inputs(version.configuration.get("inputs", []), inputs)
    except ExecutionError as error:
        problems.extend(error.problems)
        typed = {}
    if not problems:
        blocked = _concurrency_problems(db, organization_id=organization_id, workflow_id=workflow.id,
                                        limits=_limits(version.configuration))
        if blocked:
            problems.append(f"Skipped by the workflow limits: {blocked}.")
    if problems:
        persist_independent_audit_event(
            db,
            attribution=user_attribution(organization_id=organization_id, actor_user_id=run_as),
            event_type=EXECUTION_AUDIT_EVENT,
            action="workflow.event_skipped",
            decision="denied",
            outcome=OUTCOME_REQUESTED,
            permission_key=PERMISSION_RUN,
            resource_type="workflow",
            resource_id=str(workflow.id),
            metadata={"trigger_event": event_type, "reasons": problems[:5]},
        )
        return None
    return _create(db, organization_id=organization_id, workflow=workflow, version=version, run_as_user_id=run_as,
                   initiated_by=None, trigger_type="event", trigger_event=event_type, event_key=event_key,
                   source_execution_id=None, retry_of=None, idempotency_key=scoped_key, inputs=typed)


def _lock_execution(db: Session, *, organization_id: UUID, execution_id: UUID) -> WorkflowExecution:
    execution = db.scalar(select(WorkflowExecution).where(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.organization_id == organization_id,
    ).with_for_update())
    if execution is None:
        raise ExecutionError(REASON_NOT_FOUND, status=404)
    return execution


def _step_rows(db: Session, execution: WorkflowExecution) -> dict[str, WorkflowExecutionStep]:
    return {row.step_id: row for row in db.scalars(select(WorkflowExecutionStep).where(
        WorkflowExecutionStep.execution_id == execution.id)).all()}


def _record_step(db: Session, execution: WorkflowExecution, step: dict[str, Any], index: int, *, status: str,
                 attempts: int, reason: str | None, trace: dict[str, Any] | None,
                 wake_at: datetime | None = None) -> WorkflowExecutionStep:
    row = db.scalar(select(WorkflowExecutionStep).where(
        WorkflowExecutionStep.execution_id == execution.id,
        WorkflowExecutionStep.step_id == step["id"],
    ))
    if row is None:
        row = WorkflowExecutionStep(
            organization_id=execution.organization_id,
            execution_id=execution.id,
            step_id=step["id"],
            step_index=index,
            step_type=step["type"],
            status=status,
            attempts=0,
        )
        db.add(row)
    row.status = status
    row.attempts = attempts
    row.reason_code = reason
    row.trace = _bounded(trace or {}, MAX_TRACE_CHARACTERS) or {"truncated": True}
    row.wake_at = wake_at
    if status in ("succeeded", "failed", "cancelled"):
        row.finished_at = _now()
    db.flush()
    return row


def _finish(db: Session, execution: WorkflowExecution, status: str, *, reason: str | None = None,
            output: dict[str, Any] | None = None, actor_id: UUID | None = None) -> None:
    execution.status = status
    execution.failure_reason = reason
    execution.output = output
    execution.wake_at = None
    execution.finished_at = _now()
    execution.updated_at = execution.finished_at
    db.flush()
    _audit(db, execution, "workflow.execution.finished", {"reason": reason or "ok"}, actor_id=actor_id)


def _revalidate(db: Session, execution: WorkflowExecution, user_context: CurrentUserContext | None) -> str | None:
    """A stop reason when the run may not take its next step, or None when it may."""
    workflow = db.get(WorkflowDefinition, execution.workflow_id)
    if workflow is None or workflow.organization_id != execution.organization_id:
        return REASON_WORKFLOW_NOT_FOUND
    if workflow.status == WorkflowDefinition.STATUS_PAUSED:
        return REASON_WORKFLOW_PAUSED
    if workflow.status == WorkflowDefinition.STATUS_ARCHIVED:
        return REASON_WORKFLOW_ARCHIVED
    if not _membership_active(db, organization_id=execution.organization_id, user_id=execution.run_as_user_id):
        return REASON_MEMBERSHIP_REVOKED
    decision = evaluate_capability(db, organization_id=execution.organization_id, capability_key=AUTOMATION_WORKFLOWS,
                                   user_context=user_context)
    if not decision.allowed:
        return REASON_AUTOMATION_DISABLED
    return None


@dataclass
class _Outcome:
    status: str
    reason: str | None = None
    output: dict[str, Any] | None = None
    next_step: str | None = None
    wake_at: datetime | None = None
    attempts: int = 1


def _run_crm(db: Session, execution: WorkflowExecution, step: dict[str, Any], inputs: dict[str, Any],
             outputs: dict[str, dict[str, Any]], sleep: Sleep) -> _Outcome:
    arguments = {name: resolve(value, inputs, outputs) for name, value in (step.get("arguments") or {}).items()}
    if any(value is None for value in arguments.values()):
        return _Outcome("failed", REASON_BAD_REFERENCE)
    caller = WorkflowCaller(organization_id=execution.organization_id, initiated_by_user_id=execution.run_as_user_id)
    max_attempts = (step.get("retry") or {}).get("max_attempts", 1)
    attempt = 0
    while True:
        attempt += 1
        try:
            status, reason, trace = run_crm_action(db, caller, step["action"], arguments)
        except OperationalError:
            if attempt < min(max_attempts, MAX_RETRY_ATTEMPTS):
                sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            return _Outcome("dead_letter", REASON_TRANSIENT_EXHAUSTED, attempts=attempt)
        if status == "succeeded":
            return _Outcome("succeeded", None, (trace or {}).get("output") or {}, attempts=attempt)
        if status == "stopped" or reason == CRM_REASON_PERMISSION_DENIED:
            return _Outcome("stopped", reason or REASON_PERMISSION_DENIED, attempts=attempt)
        return _Outcome("failed", reason or "crm_action_failed", attempts=attempt)


def _run_agent(db: Session, execution: WorkflowExecution, step: dict[str, Any], inputs: dict[str, Any],
               outputs: dict[str, dict[str, Any]], user_context: CurrentUserContext) -> _Outcome:
    values = {name: resolve(value, inputs, outputs) for name, value in (step.get("arguments") or {}).items()}
    if any(value is None for value in values.values()):
        return _Outcome("failed", REASON_BAD_REFERENCE)
    try:
        agent_execution, _created = create_agent_execution(
            db,
            organization_id=execution.organization_id,
            agent_id=UUID(step["agent_id"]),
            user_context=user_context,
            input_values=values,
            idempotency_key=f"workflow:{execution.id}:{step['id']}",
            workflow_execution_id=execution.id,
            workflow_step_id=step["id"],
        )
    except AgentError as error:
        if error.reason == "permission_denied":
            return _Outcome("stopped", error.reason)
        return _Outcome("failed", error.reason)
    run_agent_execution(db, agent_execution, user_context)
    if agent_execution.status == AgentExecution.STATUS_WAITING_APPROVAL:
        return _Outcome("failed", REASON_AGENT_WAITING)
    if agent_execution.status != AgentExecution.STATUS_SUCCEEDED:
        return _Outcome("failed", agent_execution.failure_reason or agent_execution.status)
    result = dict(agent_execution.output or {})
    return _Outcome("succeeded", None, {"result": result.get("result"), "agent_execution_id": str(agent_execution.id)})


def _continuation(step: dict[str, Any]) -> str | None:
    return step.get("next")


def _execute(db: Session, execution: WorkflowExecution, step: dict[str, Any], index: int, inputs: dict[str, Any],
             outputs: dict[str, dict[str, Any]], user_context: CurrentUserContext | None, sleep: Sleep) -> _Outcome:
    kind = step["type"]
    if kind == "condition":
        left = resolve(step["condition"]["left"], inputs, outputs)
        result = compare(left, step["condition"]["operator"], step["condition"].get("right"))
        branch = "then" if result else "else"
        return _Outcome("succeeded", None, {"result": result, "branch": branch}, next_step=step[branch])
    if kind == "crm_action":
        outcome = _run_crm(db, execution, step, inputs, outputs, sleep)
        outcome.next_step = _continuation(step)
        return outcome
    if kind == "agent":
        outcome = _run_agent(db, execution, step, inputs, outputs, user_context or _service_context(db, execution))
        outcome.next_step = _continuation(step)
        return outcome
    if kind == "approval":
        return _Outcome("waiting_approval", step.get("reason"))
    if kind == "delay":
        seconds = min(int(step["seconds"]), MAX_DELAY_SECONDS)
        return _Outcome("waiting_timer", None, {"seconds": seconds}, wake_at=_now() + timedelta(seconds=seconds))
    return _Outcome("failed", "unsupported_step")


def _service_context(db: Session, execution: WorkflowExecution) -> CurrentUserContext:
    user = db.get(User, execution.run_as_user_id)
    return CurrentUserContext(user=user)


def run_execution(db: Session, execution: WorkflowExecution, user_context: CurrentUserContext | None, *,
                  sleep: Sleep = time.sleep, between_steps: BoundaryHook | None = None) -> WorkflowExecution:
    """Run from the next step to a terminal state or to a wait. The caller owns the transaction and commits it."""
    if execution.status in WorkflowExecution.TERMINAL_STATUSES:
        return execution
    if execution.status in (WorkflowExecution.STATUS_WAITING_APPROVAL, WorkflowExecution.STATUS_WAITING_TIMER):
        return execution
    version = db.get(WorkflowVersion, execution.version_id)
    if version is None or version.organization_id != execution.organization_id:
        _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason="version_missing")
        return execution
    config = version.configuration
    limits = _limits(config)
    steps = config["steps"]
    by_id = {step["id"]: (index, step) for index, step in enumerate(steps)}

    if execution.status == WorkflowExecution.STATUS_QUEUED:
        execution.status = WorkflowExecution.STATUS_RUNNING
        execution.started_at = execution.started_at or _now()
        execution.deadline_at = execution.deadline_at or execution.started_at + timedelta(seconds=limits["max_duration_seconds"])
        execution.next_step_id = execution.next_step_id or config["entry"]
        db.flush()
        _audit(db, execution, "workflow.execution.started", {})

    rows = _step_rows(db, execution)
    interrupted = [row for row in rows.values() if row.status == "running"]
    if interrupted:
        # A step started and never finished: its effect is unknown, so the run fails rather than repeating the step.
        for row in interrupted:
            row.status = "failed"
            row.reason_code = REASON_INTERRUPTED
            row.finished_at = _now()
        _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason=REASON_INTERRUPTED)
        return execution

    inputs = dict(execution.input_values or {})
    outputs = {step_id: dict(row.trace.get("output") or {}) for step_id, row in rows.items()
               if row.status == "succeeded" and row.trace and isinstance(row.trace.get("output"), dict)}

    while True:
        if between_steps is not None:
            between_steps(db, execution)
        if execution.cancel_requested_at is not None:
            _finish(db, execution, WorkflowExecution.STATUS_CANCELLED, reason=REASON_CANCEL)
            return execution
        if execution.deadline_at is not None and _now() >= execution.deadline_at:
            _finish(db, execution, WorkflowExecution.STATUS_TIMED_OUT, reason=REASON_DEADLINE)
            return execution
        stop = _revalidate(db, execution, user_context)
        if stop is not None:
            _finish(db, execution, WorkflowExecution.STATUS_STOPPED, reason=stop)
            return execution

        current = execution.next_step_id
        if current is None:
            output = {name: resolve(ref, inputs, outputs) for name, ref in (config.get("outputs") or {}).items()}
            bounded = _bounded(output, MAX_OUTPUT_CHARACTERS)
            if bounded is None:
                _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason=REASON_OUTPUT_TOO_LARGE)
            else:
                _finish(db, execution, WorkflowExecution.STATUS_SUCCEEDED, output=bounded)
            return execution
        if execution.steps_completed >= limits["max_steps"]:
            _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason=REASON_STEP_LIMIT)
            return execution
        index, step = by_id[current]
        spec = _approval_spec(step)
        if spec is not None:
            verdict, reason = _pass_gate(db, execution, step, index, spec, inputs, outputs, now=_now())
            if verdict == "waiting":
                execution.status = WorkflowExecution.STATUS_WAITING_APPROVAL
                execution.updated_at = _now()
                db.flush()
                _audit(db, execution, "workflow.execution.waiting_approval", {"step_id": step["id"]})
                return execution
            if verdict == "failed":
                _record_step(db, execution, step, index, status="failed", attempts=1, reason=reason, trace=None)
                _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason=reason)
                return execution
            if verdict == "approved_step":
                row = _record_step(db, execution, step, index, status="succeeded", attempts=1, reason=None,
                                   trace={"output": {"decision": "approved"}})
                task = _find_task(db, execution, step["id"])
                row.decided_by_user_id = task.decided_by_user_id if task is not None else None
                outputs[step["id"]] = {"decision": "approved"}
                execution.steps_completed += 1
                execution.next_step_id = step.get("next")
                execution.updated_at = _now()
                db.flush()
                continue
        _record_step(db, execution, step, index, status="running", attempts=0, reason=None, trace=None)

        outcome = _execute(db, execution, step, index, inputs, outputs, user_context, sleep)
        if outcome.status == "waiting_approval":
            _record_step(db, execution, step, index, status="waiting_approval", attempts=1, reason=None,
                         trace={"reason": outcome.reason, "approver_permission": step.get("approver_permission")})
            execution.status = WorkflowExecution.STATUS_WAITING_APPROVAL
            execution.updated_at = _now()
            db.flush()
            _audit(db, execution, "workflow.execution.waiting_approval", {"step_id": step["id"]})
            return execution
        if outcome.status == "waiting_timer":
            _record_step(db, execution, step, index, status="waiting_timer", attempts=1, reason=None,
                         trace={"seconds": (outcome.output or {}).get("seconds")}, wake_at=outcome.wake_at)
            execution.status = WorkflowExecution.STATUS_WAITING_TIMER
            execution.wake_at = outcome.wake_at
            execution.updated_at = _now()
            db.flush()
            _audit(db, execution, "workflow.execution.waiting_timer", {"step_id": step["id"]})
            return execution
        if outcome.status == "succeeded":
            _record_step(db, execution, step, index, status="succeeded", attempts=outcome.attempts, reason=None,
                         trace={"output": outcome.output or {}, "branch": (outcome.output or {}).get("branch")})
            outputs[step["id"]] = dict(outcome.output or {})
            execution.steps_completed += 1
            execution.next_step_id = outcome.next_step
            execution.updated_at = _now()
            db.flush()
            continue
        _record_step(db, execution, step, index, status="failed", attempts=outcome.attempts, reason=outcome.reason,
                     trace=None)
        terminal = {"stopped": WorkflowExecution.STATUS_STOPPED,
                    "dead_letter": WorkflowExecution.STATUS_DEAD_LETTER}.get(outcome.status,
                                                                             WorkflowExecution.STATUS_FAILED)
        _finish(db, execution, terminal, reason=outcome.reason)
        return execution


def handle_execution_requested(db: Session, execution_id: UUID, organization_id: UUID) -> None:
    """Outbox handler body: run a queued run, or resume it after its wait. Duplicate deliveries do nothing."""
    execution = _lock_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution.status not in (WorkflowExecution.STATUS_QUEUED, WorkflowExecution.STATUS_RUNNING):
        return
    user = db.get(User, execution.run_as_user_id)
    if user is None:
        _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason="run_as_missing")
        return
    run_execution(db, execution, CurrentUserContext(user=user))


def _resume_queued(db: Session, execution: WorkflowExecution, next_step: str | None) -> None:
    execution.status = WorkflowExecution.STATUS_QUEUED
    execution.next_step_id = next_step
    execution.wake_at = None
    execution.updated_at = _now()
    db.flush()
    _enqueue(db, execution, token=uuid.uuid4().hex)


def decide_approval(db: Session, *, organization_id: UUID, user_context: CurrentUserContext, execution_id: UUID,
                    step_id: str, approve: bool, reason: str | None) -> WorkflowExecution:
    """Approve or reject the step a run waits on, through its human task. The rules are in ``decide_workflow_task``."""
    execution = _lock_execution(db, organization_id=organization_id, execution_id=execution_id)
    if execution.status != WorkflowExecution.STATUS_WAITING_APPROVAL or execution.next_step_id != step_id:
        raise ExecutionError(REASON_NOT_WAITING)
    task = _find_task(db, execution, step_id)
    if task is None:
        raise ExecutionError(REASON_NOT_WAITING)
    decide_workflow_task(db, organization_id=organization_id, user_context=user_context, task_id=task.id,
                         approve=approve, comment=reason)
    return execution


def _find_task(db: Session, execution: WorkflowExecution, step_id: str) -> HumanTask | None:
    return db.scalar(select(HumanTask).where(
        HumanTask.organization_id == execution.organization_id,
        HumanTask.workflow_execution_id == execution.id,
        HumanTask.workflow_step_id == step_id,
    ))


def _fail_waiting(db: Session, execution: WorkflowExecution, step_id: str, reason: str,
                  actor_id: UUID | None = None) -> None:
    """End a run that waits on a step with a failure reason. The waiting step record is closed with the same reason."""
    row = _step_rows(db, execution).get(step_id)
    if row is not None:
        row.status = "failed"
        row.reason_code = reason
        row.finished_at = _now()
    _finish(db, execution, WorkflowExecution.STATUS_FAILED, reason=reason, actor_id=actor_id)


def decide_workflow_task(db: Session, *, organization_id: UUID, user_context: CurrentUserContext, task_id: UUID,
                         approve: bool, comment: str | None = None) -> tuple[HumanTask, bool]:
    """Record a decision on a human task and resume or end its run. Returns ``(task, changed)``.

    The task service checks the decider (active membership, permission, assignment, separation of duties) and the single final
    outcome. A repeated decision changes nothing. A rejection ends the run; an approval queues it, and the run checks the approval
    for the exact payload when it reaches the step.
    """
    decider = user_context.user.id
    try:
        task, changed = human_tasks.decide(db, organization_id=organization_id, actor_id=decider, task_id=task_id,
                                           approve=approve, comment_text=comment)
    except human_tasks.TaskError as error:
        if error.reason == human_tasks.REASON_EXPIRED:
            expired = db.get(HumanTask, task_id)
            if expired is not None and expired.workflow_execution_id is not None:
                execution = _lock_execution(db, organization_id=organization_id,
                                            execution_id=expired.workflow_execution_id)
                if (execution.status == WorkflowExecution.STATUS_WAITING_APPROVAL
                        and execution.next_step_id == expired.workflow_step_id):
                    _fail_waiting(db, execution, expired.workflow_step_id, "approval_expired")
        raise ExecutionError(error.reason, error.problems, status=error.status) from error
    if changed and task.workflow_execution_id is not None:
        execution = _lock_execution(db, organization_id=organization_id, execution_id=task.workflow_execution_id)
        if execution.status == WorkflowExecution.STATUS_WAITING_APPROVAL and execution.next_step_id == task.workflow_step_id:
            if approve:
                _resume_queued(db, execution, execution.next_step_id)
            else:
                _fail_waiting(db, execution, task.workflow_step_id, "approval_rejected", actor_id=decider)
    return task, changed


def cancel_workflow_task(db: Session, *, organization_id: UUID, user_context: CurrentUserContext, task_id: UUID,
                         reason: str | None = None) -> HumanTask:
    """Cancel a pending task. A run waiting on it ends with ``approval_cancelled``."""
    try:
        task = human_tasks.cancel(db, organization_id=organization_id, actor_id=user_context.user.id, task_id=task_id,
                                  reason=reason)
    except human_tasks.TaskError as error:
        raise ExecutionError(error.reason, error.problems, status=error.status) from error
    if task.workflow_execution_id is not None:
        execution = _lock_execution(db, organization_id=organization_id, execution_id=task.workflow_execution_id)
        if (execution.status == WorkflowExecution.STATUS_WAITING_APPROVAL
                and execution.next_step_id == task.workflow_step_id):
            _fail_waiting(db, execution, task.workflow_step_id, "approval_cancelled", actor_id=user_context.user.id)
    return task


def expire_workflow_tasks(db: Session, *, organization_id: UUID, now: datetime | None = None) -> int:
    """Expire the pending tasks whose due time has passed, and end the runs waiting on them. Bounded per call."""
    expired = human_tasks.expire_due(db, organization_id=organization_id, now=now)
    for task in expired:
        if task.workflow_execution_id is None:
            continue
        execution = _lock_execution(db, organization_id=organization_id, execution_id=task.workflow_execution_id)
        if execution.status == WorkflowExecution.STATUS_WAITING_APPROVAL and execution.next_step_id == task.workflow_step_id:
            _fail_waiting(db, execution, task.workflow_step_id, "approval_expired")
    return len(expired)


def _approval_spec(step: dict[str, Any]) -> dict[str, Any] | None:
    """The approval a step needs before it runs: an explicit approval step, or a configured gate on a sensitive action."""
    if step["type"] == "approval":
        return {"approver_permission": step["approver_permission"],
                "expires_after_seconds": step.get("expires_after_seconds", DEFAULT_APPROVAL_EXPIRY_SECONDS)}
    gate = step.get("approval")
    return dict(gate) if gate else None


def _gate_payload(execution: WorkflowExecution, step: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """The exact payload an approval covers: this run, this step, the pinned version and the resolved arguments."""
    return json.loads(json.dumps({"execution_id": str(execution.id), "step_id": step["id"],
                                  "version_id": str(execution.version_id), "arguments": arguments},
                                 sort_keys=True, default=str))


def _pass_gate(db: Session, execution: WorkflowExecution, step: dict[str, Any], index: int, spec: dict[str, Any],
               inputs: dict[str, Any], outputs: dict[str, dict[str, Any]], *, now: datetime) -> tuple[str, str | None]:
    """Open, wait on, or pass the approval for this step. Returns ``(verdict, reason)``.

    Verdicts: ``waiting`` (a task is open and undecided), ``failed`` (the reason ends the run), ``approved_step`` (an explicit
    approval step passed), or ``proceed`` (a gated action may run now; its approval has been consumed).
    """
    arguments = {} if step["type"] == "approval" else {
        name: resolve(value, inputs, outputs) for name, value in (step.get("arguments") or {}).items()}
    payload = _gate_payload(execution, step, arguments)
    task = _find_task(db, execution, step["id"])
    if task is None:
        expires = int(spec["expires_after_seconds"])
        task, _created = human_tasks.create_task(
            db,
            organization_id=execution.organization_id,
            requested_by_user_id=execution.run_as_user_id,
            title=f"Approve step {step['id']}",
            instructions=step.get("reason") or "Decide whether this workflow run may continue.",
            required_permission=spec["approver_permission"],
            due_at=now + timedelta(seconds=expires),
            payload=payload,
            capability_key=AUTOMATION_WORKFLOWS,
            resource_type="workflow_execution",
            resource_id=str(execution.id),
            workflow_execution_id=execution.id,
            workflow_step_id=step["id"],
            now=now,
        )
        _record_step(db, execution, step, index, status="waiting_approval", attempts=1, reason=None,
                     trace={"task_id": str(task.id), "approver_permission": spec["approver_permission"]})
        return "waiting", None
    if task.status == HumanTask.STATUS_PENDING:
        if task.due_at is not None and now >= task.due_at:
            human_tasks.expire_task(db, task, now=now)
            return "failed", "approval_expired"
        return "waiting", None
    if task.status == HumanTask.STATUS_APPROVED:
        approval = db.get(ApprovalRequest, task.approval_request_id)
        if approval is None or approval.payload_hash != payload_hash(payload):
            return "failed", "approval_mismatch"
        try:
            check_approval_for_execution(
                db, organization_id=execution.organization_id, approval_id=task.approval_request_id,
                capability_key=AUTOMATION_WORKFLOWS, resource_type="workflow_execution", resource_id=str(execution.id),
                payload=payload, now=now)
            consume_approval(db, organization_id=execution.organization_id, approval_id=task.approval_request_id,
                             actor_user_id=execution.run_as_user_id, now=now)
        except ApprovalError as error:
            return "failed", error.reason_code
        if step["type"] == "approval":
            return "approved_step", None
        return "proceed", None
    mapping = {HumanTask.STATUS_REJECTED: "approval_rejected", HumanTask.STATUS_EXPIRED: "approval_expired",
               HumanTask.STATUS_CANCELLED: "approval_cancelled"}
    return "failed", mapping.get(task.status, "approval_unavailable")


def resume_due_timers(db: Session, *, organization_id: UUID, now: datetime | None = None) -> int:
    """Resume runs whose delay has elapsed. Bounded per call. Returns how many were resumed."""
    moment = now or _now()
    due = db.scalars(select(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id,
        WorkflowExecution.status == WorkflowExecution.STATUS_WAITING_TIMER,
        WorkflowExecution.wake_at <= moment,
    ).order_by(WorkflowExecution.wake_at).limit(DUE_TIMER_BATCH).with_for_update()).all()
    for execution in due:
        version = db.get(WorkflowVersion, execution.version_id)
        waiting = next((step for step in version.configuration["steps"]
                        if step["id"] == execution.next_step_id), None)
        rows = _step_rows(db, execution)
        row = rows.get(execution.next_step_id)
        if waiting is not None and row is not None:
            index = next(i for i, item in enumerate(version.configuration["steps"]) if item["id"] == waiting["id"])
            _record_step(db, execution, waiting, index, status="succeeded", attempts=1, reason=None,
                         trace={"output": {"waited": True}})
            _audit(db, execution, "workflow.execution.resumed", {"step_id": waiting["id"]})
            _resume_queued(db, execution, waiting.get("next"))
    return len(due)


def request_cancel(db: Session, *, organization_id: UUID, user_context: CurrentUserContext,
                   execution_id: UUID) -> WorkflowExecution:
    actor = user_context.user.id
    execution = _lock_execution(db, organization_id=organization_id, execution_id=execution_id)
    if actor != execution.run_as_user_id and not actor_permission_granted(
            db, organization_id=organization_id, user_id=actor, permission_key=PERMISSION_RUN):
        raise ExecutionError(REASON_PERMISSION_DENIED, status=403)
    if execution.status in WorkflowExecution.TERMINAL_STATUSES:
        raise ExecutionError(REASON_NOT_CANCELLABLE)
    execution.cancel_requested_at = _now()
    if execution.status in (WorkflowExecution.STATUS_QUEUED, WorkflowExecution.STATUS_WAITING_APPROVAL,
                            WorkflowExecution.STATUS_WAITING_TIMER):
        human_tasks.cancel_for_execution(db, organization_id=organization_id, workflow_execution_id=execution.id,
                                         reason=REASON_CANCEL)
        for row in _step_rows(db, execution).values():
            if row.status in ("waiting_approval", "waiting_timer"):
                row.status = "cancelled"
                row.finished_at = _now()
        _finish(db, execution, WorkflowExecution.STATUS_CANCELLED, reason=REASON_CANCEL, actor_id=actor)
    return execution


def retry_run(db: Session, *, organization_id: UUID, user_context: CurrentUserContext,
              execution_id: UUID) -> tuple[WorkflowExecution, bool]:
    """Start a new run with the same pinned version and input. Authorization is checked again for the member who asks."""
    actor = user_context.user.id
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor, permission_key=PERMISSION_RUN):
        raise ExecutionError(REASON_PERMISSION_DENIED, status=403)
    original = db.scalar(select(WorkflowExecution).where(
        WorkflowExecution.id == execution_id, WorkflowExecution.organization_id == organization_id))
    if original is None:
        raise ExecutionError(REASON_NOT_FOUND, status=404)
    if original.status not in WorkflowExecution.RETRYABLE_STATUSES:
        raise ExecutionError(REASON_NOT_RETRYABLE)
    key = f"retry:{original.id}"
    existing = db.scalar(select(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id, WorkflowExecution.idempotency_key == key))
    if existing is not None:
        return existing, False
    workflow = _lock_workflow(db, organization_id=organization_id, workflow_id=original.workflow_id)
    version = db.get(WorkflowVersion, original.version_id)
    problems = _start_problems(db, organization_id=organization_id, workflow=workflow, version=version,
                               run_as_user_id=actor, user_context=user_context)
    if problems:
        raise ExecutionError(REASON_NOT_RUNNABLE, problems)
    blocked = _concurrency_problems(db, organization_id=organization_id, workflow_id=workflow.id,
                                    limits=_limits(version.configuration))
    if blocked:
        raise ExecutionError(blocked, status=429)
    execution = _create(db, organization_id=organization_id, workflow=workflow, version=version, run_as_user_id=actor,
                        initiated_by=actor, trigger_type=original.trigger_type, trigger_event=original.trigger_event,
                        event_key=None, source_execution_id=None, retry_of=original.id, idempotency_key=key,
                        inputs=dict(original.input_values or {}))
    return execution, True


def expire_stale_running(db: Session, *, organization_id: UUID) -> int:
    """Finish running runs whose deadline has passed and that no worker is advancing. Returns how many."""
    stale = db.scalars(select(WorkflowExecution).where(
        WorkflowExecution.organization_id == organization_id,
        WorkflowExecution.status == WorkflowExecution.STATUS_RUNNING,
        WorkflowExecution.deadline_at < _now(),
    ).with_for_update()).all()
    for execution in stale:
        _finish(db, execution, WorkflowExecution.STATUS_TIMED_OUT, reason=REASON_DEADLINE)
    return len(stale)
