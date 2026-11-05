"""Workflow runs over HTTP: start, read, cancel, retry, approve or reject, and resume due timers (DFR1-024).

Every route is scoped to the verified organization. Reading needs ``workflows.read``. Starting, cancelling, retrying and resuming
timers need ``workflows.run``. An approval needs the approver permission named by the approval step, and the decider cannot be the
member the run acts as. The run response carries the pinned version number, the trigger, the step records and the failure reason.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.workflow import WorkflowVersion
from app.db.models.workflow_execution import WorkflowExecution, WorkflowExecutionStep
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext, get_tenant_context
from app.workflows.runtime import (
    ExecutionError,
    decide_approval,
    expire_stale_running,
    request_cancel,
    resume_due_timers,
    retry_run,
    start_manual,
)

router = APIRouter(prefix="/api/v1/automation", tags=["workflow-runs"])


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


def _raise(error: ExecutionError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _step_body(row: WorkflowExecutionStep) -> dict[str, Any]:
    return {
        "step_id": row.step_id,
        "step_index": row.step_index,
        "type": row.step_type,
        "status": row.status,
        "attempts": row.attempts,
        "reason_code": row.reason_code,
        "trace": row.trace,
        "wake_at": row.wake_at.isoformat() if row.wake_at else None,
        "decided_by_user_id": str(row.decided_by_user_id) if row.decided_by_user_id else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def _summary(row: WorkflowExecution) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workflow_id": str(row.workflow_id),
        "status": row.status,
        "version_id": str(row.version_id),
        "version_number": row.version_number,
        "trigger": {
            "type": row.trigger_type,
            "event": row.trigger_event,
            "event_key": row.event_key,
            "source_execution_id": str(row.source_execution_id) if row.source_execution_id else None,
        },
        "retry_of_execution_id": str(row.retry_of_execution_id) if row.retry_of_execution_id else None,
        "run_as_user_id": str(row.run_as_user_id),
        "initiated_by_user_id": str(row.initiated_by_user_id) if row.initiated_by_user_id else None,
        "failure_reason": row.failure_reason,
        "steps_completed": row.steps_completed,
        "next_step_id": row.next_step_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
        "output": row.output,
    }


def _detail(db: Session, row: WorkflowExecution) -> dict[str, Any]:
    steps = db.scalars(select(WorkflowExecutionStep).where(
        WorkflowExecutionStep.execution_id == row.id,
        WorkflowExecutionStep.organization_id == row.organization_id,
    ).order_by(WorkflowExecutionStep.step_index)).all()
    version = db.get(WorkflowVersion, row.version_id)
    pending = None
    if row.status == WorkflowExecution.STATUS_WAITING_APPROVAL and version is not None:
        step = next((item for item in version.configuration["steps"] if item["id"] == row.next_step_id), None)
        if step is not None:
            pending = {"step_id": step["id"], "approver_permission": step.get("approver_permission"),
                       "reason": step.get("reason")}
    return dict(_summary(row), steps=[_step_body(item) for item in steps], pending_approval=pending)


@router.post("/workflows/{workflow_id}/executions", status_code=status.HTTP_202_ACCEPTED)
def start_endpoint(
    workflow_id: UUID,
    payload: StartRunRequest,
    response: Response,
    tenant: TenantContext = Depends(require_permission("workflows.run")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Start a run. Returns 202 with the new run, or 200 with the stored run when the same key and input were used before."""
    try:
        row, created = start_manual(db, organization_id=tenant.organization_id, user_context=user_context,
                                    workflow_id=workflow_id, input_values=payload.input,
                                    idempotency_key=payload.idempotency_key)
        db.commit()
    except ExecutionError as error:
        db.rollback()
        _raise(error)
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return dict(_detail(db, row), created=created)


@router.get("/workflows/{workflow_id}/executions")
def list_endpoint(
    workflow_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = db.scalars(select(WorkflowExecution).where(
        WorkflowExecution.organization_id == tenant.organization_id,
        WorkflowExecution.workflow_id == workflow_id,
    ).order_by(WorkflowExecution.created_at.desc(), WorkflowExecution.id.desc()).limit(limit)).all()
    return {"items": [_summary(row) for row in rows]}


@router.get("/executions/{execution_id}")
def get_endpoint(
    execution_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    row = db.scalar(select(WorkflowExecution).where(
        WorkflowExecution.id == execution_id, WorkflowExecution.organization_id == tenant.organization_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"reason": "execution_not_found"})
    return _detail(db, row)


@router.post("/executions/{execution_id}/cancel")
def cancel_endpoint(
    execution_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Cancel a run. Queued and waiting runs stop now; a running run stops at its next boundary."""
    try:
        row = request_cancel(db, organization_id=tenant.organization_id, user_context=user_context, execution_id=execution_id)
        db.commit()
    except ExecutionError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.post("/executions/{execution_id}/retry", status_code=status.HTTP_201_CREATED)
def retry_endpoint(
    execution_id: UUID,
    response: Response,
    tenant: TenantContext = Depends(require_permission("workflows.run")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row, created = retry_run(db, organization_id=tenant.organization_id, user_context=user_context,
                                 execution_id=execution_id)
        db.commit()
    except ExecutionError as error:
        db.rollback()
        _raise(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return dict(_detail(db, row), created=created)


@router.post("/executions/{execution_id}/steps/{step_id}/decision")
def decision_endpoint(
    execution_id: UUID,
    step_id: str,
    payload: DecisionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Approve or reject the approval step a run waits on. The approver permission of that step is checked."""
    try:
        row = decide_approval(db, organization_id=tenant.organization_id, user_context=user_context,
                              execution_id=execution_id, step_id=step_id,
                              approve=payload.decision == "approve", reason=payload.reason)
        db.commit()
    except ExecutionError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.post("/executions/resume-due")
def resume_due_endpoint(
    tenant: TenantContext = Depends(require_permission("workflows.run")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Resume the runs whose delay has elapsed in this organization. Bounded per call."""
    resumed = resume_due_timers(db, organization_id=tenant.organization_id)
    db.commit()
    return {"resumed": resumed}


@router.post("/executions/expire-stale")
def expire_endpoint(
    tenant: TenantContext = Depends(require_permission("workflows.run")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    expired = expire_stale_running(db, organization_id=tenant.organization_id)
    db.commit()
    return {"expired": expired}


__all__ = ["router"]
