"""Human tasks over HTTP: list, read, decide, comment, assign, cancel and expire (DFR1-025).

Every route is scoped to the verified organization. Reading and deciding need an active membership. The service checks what each
caller may do: visibility, the task's permission, the assignee, separation of duties and the single final outcome. Assigning,
cancelling and expiring need ``human_tasks.manage``. A task that belongs to a workflow run is decided, cancelled or expired through
the run, so the run resumes or ends in the same transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.human_task import HumanTask, HumanTaskEvent
from app.db.session import get_db_session
from app.human_tasks import service as human_tasks
from app.tenant.dependencies import TenantContext, get_tenant_context
from app.workflows.runtime import (
    ExecutionError,
    cancel_workflow_task,
    decide_workflow_task,
    expire_workflow_tasks,
)

router = APIRouter(prefix="/api/v1/human-tasks", tags=["human-tasks"])


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)


class CommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: UUID
    expected_version: int = Field(ge=1)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


def _raise_task(error: human_tasks.TaskError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _raise_run(error: ExecutionError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _task_body(task: HumanTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "kind": task.kind,
        "status": task.status,
        "title": task.title,
        "instructions": task.instructions,
        "required_permission": task.required_permission,
        "assigned_to_user_id": str(task.assigned_to_user_id)
        if task.assigned_to_user_id
        else None,
        "requested_by_user_id": str(task.requested_by_user_id),
        "decided_by_user_id": str(task.decided_by_user_id)
        if task.decided_by_user_id
        else None,
        "decided_at": _iso(task.decided_at),
        "decision_comment": task.decision_comment,
        "due_at": _iso(task.due_at),
        "version": task.version,
        "workflow_execution_id": str(task.workflow_execution_id)
        if task.workflow_execution_id
        else None,
        "workflow_step_id": task.workflow_step_id,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }


def _event_body(event: HumanTaskEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "from_user_id": str(event.from_user_id) if event.from_user_id else None,
        "to_user_id": str(event.to_user_id) if event.to_user_id else None,
        "comment": event.comment,
        "created_at": _iso(event.created_at),
    }


def _detail(
    db: Session, task: HumanTask, *, actor_id: UUID, organization_id: UUID
) -> dict[str, Any]:
    events = human_tasks.list_events(
        db, organization_id=organization_id, actor_id=actor_id, task_id=task.id
    )
    return dict(_task_body(task), events=[_event_body(event) for event in events])


@router.get("")
def list_endpoint(
    status_filter: Literal["pending", "approved", "rejected", "cancelled", "expired"]
    | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    tenant: TenantContext = Depends(get_tenant_context),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = human_tasks.list_tasks(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            status=status_filter,
            limit=limit,
        )
    except human_tasks.TaskError as error:
        _raise_task(error)
    return {"items": [_task_body(row) for row in rows]}


@router.get("/{task_id}")
def get_endpoint(
    task_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        task = human_tasks.get_task(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            task_id=task_id,
        )
    except human_tasks.TaskError as error:
        _raise_task(error)
    return _detail(
        db, task, actor_id=user_context.user.id, organization_id=tenant.organization_id
    )


@router.post("/{task_id}/decision")
def decision_endpoint(
    task_id: UUID,
    payload: DecisionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Approve or reject a task. A repeat of the same decision by the same member changes nothing and returns ``changed: false``."""
    approve = payload.decision == "approve"
    try:
        task = human_tasks.get_task(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            task_id=task_id,
        )
        if task.workflow_execution_id is not None:
            task, changed = decide_workflow_task(
                db,
                organization_id=tenant.organization_id,
                user_context=user_context,
                task_id=task_id,
                approve=approve,
                comment=payload.comment,
            )
        else:
            task, changed = human_tasks.decide(
                db,
                organization_id=tenant.organization_id,
                actor_id=user_context.user.id,
                task_id=task_id,
                approve=approve,
                comment_text=payload.comment,
            )
        db.commit()
    except ExecutionError as error:
        # An expired task is expired in the database before the refusal. That change must persist, so it is committed.
        _finish_refused(db, expired=error.reason == human_tasks.REASON_EXPIRED)
        _raise_run(error)
    except human_tasks.TaskError as error:
        _finish_refused(db, expired=error.reason == human_tasks.REASON_EXPIRED)
        _raise_task(error)
    return dict(_task_body(task), changed=changed)


@router.post("/{task_id}/comments", status_code=201)
def comment_endpoint(
    task_id: UUID,
    payload: CommentRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        task = human_tasks.comment(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            task_id=task_id,
            text=payload.text,
        )
        db.commit()
    except human_tasks.TaskError as error:
        db.rollback()
        _raise_task(error)
    return _detail(
        db, task, actor_id=user_context.user.id, organization_id=tenant.organization_id
    )


@router.post("/{task_id}/assignment")
def assign_endpoint(
    task_id: UUID,
    payload: AssignRequest,
    tenant: TenantContext = Depends(require_permission(human_tasks.MANAGE_PERMISSION)),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        task = human_tasks.assign(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            task_id=task_id,
            assignee_user_id=payload.assignee_user_id,
            expected_version=payload.expected_version,
        )
        db.commit()
    except human_tasks.TaskError as error:
        db.rollback()
        _raise_task(error)
    return _task_body(task)


@router.post("/{task_id}/cancel")
def cancel_endpoint(
    task_id: UUID,
    payload: CancelRequest,
    tenant: TenantContext = Depends(require_permission(human_tasks.MANAGE_PERMISSION)),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        existing = human_tasks.get_task(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            task_id=task_id,
        )
        if existing.workflow_execution_id is not None:
            task = cancel_workflow_task(
                db,
                organization_id=tenant.organization_id,
                user_context=user_context,
                task_id=task_id,
                reason=payload.reason,
            )
        else:
            task = human_tasks.cancel(
                db,
                organization_id=tenant.organization_id,
                actor_id=user_context.user.id,
                task_id=task_id,
                reason=payload.reason,
            )
        db.commit()
    except ExecutionError as error:
        db.rollback()
        _raise_run(error)
    except human_tasks.TaskError as error:
        db.rollback()
        _raise_task(error)
    return _task_body(task)


@router.post("/expire-due")
def expire_endpoint(
    tenant: TenantContext = Depends(require_permission(human_tasks.MANAGE_PERMISSION)),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Expire the pending tasks whose due time has passed, and end the runs waiting on them. Bounded per call."""
    expired = expire_workflow_tasks(
        db, organization_id=tenant.organization_id, now=datetime.now(UTC)
    )
    db.commit()
    return {"expired": expired}


def _finish_refused(db: Session, *, expired: bool) -> None:
    if expired:
        db.commit()
    else:
        db.rollback()


__all__ = ["router"]
