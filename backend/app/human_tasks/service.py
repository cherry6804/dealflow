"""Human tasks: creation, assignment, decisions, cancellation and expiry (DFR1-025).

A human task reuses the governance approval lifecycle for the decision itself (``app/governance/approvals.py``): the approval binds the
exact payload by hash, enforces that the requester cannot decide, expires, and is consumed once. This module adds what a workflow needs
on top of it: who may decide (the assignee, or any active member holding the task's permission), a single final outcome, an append-only
event history, and the in-app notice to an assignee.

Rules enforced here, on the server, for every call:

- The acting member must be an active member of the organization (checked against the database).
- A decision needs the task's required permission, and, when the task is assigned, the assignee.
- The member who asked for the decision (the run-as member) cannot decide it (separation of duties).
- Only a pending task can be decided. A repeated decision by the same member with the same outcome changes nothing. Any other
  repeated or conflicting decision is refused and the first decision stands.
- A decision after the due time expires the task instead of deciding it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.attribution import (
    register_system_actor,
    system_attribution,
    user_attribution,
)
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.db.models.approval_request import ApprovalRequest
from app.db.models.human_task import HumanTask, HumanTaskEvent
from app.db.models.membership import Membership
from app.governance.approvals import (
    REASON_APPROVAL_EXPIRED,
    REASON_APPROVAL_NOT_FOUND,
    REASON_APPROVAL_NOT_PENDING,
    REASON_SELF_APPROVAL,
    ApprovalError,
    decide_approval,
    request_approval,
)
from app.governance.execution_gate import actor_permission_granted
from app.notifications.service import create_notification

HUMAN_TASK_AUDIT_EVENT = "human_task"
MANAGE_PERMISSION = "human_tasks.manage"
NOTIFICATION_ASSIGNED = "HUMAN_TASK_ASSIGNED"
MAX_TITLE = 200
MAX_INSTRUCTIONS = 1000
MAX_COMMENT = 1000
HUMAN_TASK_SYSTEM_ACTOR = register_system_actor("human_tasks")

REASON_NOT_FOUND = "task_not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_MEMBERSHIP_INACTIVE = "membership_inactive"
REASON_NOT_ASSIGNEE = "not_assignee"
REASON_SELF_DECISION = "self_approval_refused"
REASON_ALREADY_DECIDED = "already_decided"
REASON_NOT_PENDING = "task_not_pending"
REASON_EXPIRED = "task_expired"
REASON_VERSION_CONFLICT = "version_conflict"
REASON_ASSIGNEE_NOT_ELIGIBLE = "assignee_not_eligible"
REASON_INVALID_DECISION = "invalid_decision"
REASON_APPROVAL_MISSING = "approval_not_found"


class TaskError(Exception):
    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def _membership_active(db: Session, *, organization_id: UUID, user_id: UUID) -> bool:
    return db.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id,
        Membership.user_id == user_id,
        Membership.is_active.is_(True),
    )) is not None


def is_eligible(db: Session, *, organization_id: UUID, user_id: UUID, permission: str) -> bool:
    """An active member who holds the permission. Used for assignment and for visibility."""
    return _membership_active(db, organization_id=organization_id, user_id=user_id) and actor_permission_granted(
        db, organization_id=organization_id, user_id=user_id, permission_key=permission)


def _attribution(db: Session, *, organization_id: UUID, actor_id: UUID):
    if _membership_active(db, organization_id=organization_id, user_id=actor_id):
        return user_attribution(organization_id=organization_id, actor_user_id=actor_id)
    return system_attribution(organization_id=organization_id, capability=HUMAN_TASK_SYSTEM_ACTOR)


def _audit(db: Session, task: HumanTask, *, actor_id: UUID, action: str, metadata: dict[str, Any]) -> None:
    # Identifiers, statuses and outcomes only. Comments and instructions are never written to the audit trail.
    persist_independent_audit_event(
        db,
        attribution=_attribution(db, organization_id=task.organization_id, actor_id=actor_id),
        event_type=HUMAN_TASK_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key=task.required_permission,
        resource_type="human_task",
        resource_id=str(task.id),
        metadata=dict(metadata, status=task.status, version=task.version, kind=task.kind),
    )


def _event(db: Session, task: HumanTask, *, event_type: str, actor_id: UUID | None, from_user: UUID | None = None,
           to_user: UUID | None = None, comment: str | None = None, detail: dict[str, Any] | None = None) -> None:
    db.add(HumanTaskEvent(
        organization_id=task.organization_id,
        task_id=task.id,
        event_type=event_type,
        actor_user_id=actor_id,
        from_user_id=from_user,
        to_user_id=to_user,
        comment=(comment or "").strip()[:MAX_COMMENT] or None,
        detail=detail,
    ))
    db.flush()


def _lock(db: Session, *, organization_id: UUID, task_id: UUID) -> HumanTask:
    task = db.scalar(select(HumanTask).where(
        HumanTask.id == task_id, HumanTask.organization_id == organization_id,
    ).with_for_update())
    if task is None:
        raise TaskError(REASON_NOT_FOUND, status=404)
    return task


def _require_manage(db: Session, *, organization_id: UUID, actor_id: UUID) -> None:
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=MANAGE_PERMISSION):
        raise TaskError(REASON_PERMISSION_DENIED, status=403)


def _notify(db: Session, task: HumanTask, recipient: UUID) -> None:
    create_notification(
        db,
        organization_id=task.organization_id,
        recipient_user_id=recipient,
        event_type=NOTIFICATION_ASSIGNED,
        title="A decision is waiting for you",
        message="You have been asked to decide a workflow approval in Dealsflo.",
        resource_type="human_task",
        resource_id=str(task.id),
        event_key=f"human_task:{task.id}:assigned:{recipient}:{task.version}",
    )


def create_task(
    db: Session,
    *,
    organization_id: UUID,
    requested_by_user_id: UUID,
    title: str,
    instructions: str | None,
    required_permission: str,
    due_at: datetime,
    payload: Mapping[str, object],
    capability_key: str,
    resource_type: str,
    resource_id: str,
    assignee_user_id: UUID | None = None,
    workflow_execution_id: UUID | None = None,
    workflow_step_id: str | None = None,
    now: datetime | None = None,
) -> tuple[HumanTask, bool]:
    """Create an approval task bound to one exact payload. Returns ``(task, created)``.

    A task for the same workflow execution and step is returned, not created again. The governance approval has the same expiry
    as the task.
    """
    current = now or datetime.now(UTC)
    if workflow_execution_id is not None and workflow_step_id is not None:
        existing = db.scalar(select(HumanTask).where(
            HumanTask.organization_id == organization_id,
            HumanTask.workflow_execution_id == workflow_execution_id,
            HumanTask.workflow_step_id == workflow_step_id,
        ))
        if existing is not None:
            return existing, False
    clean_title = title.strip()[:MAX_TITLE]
    if not clean_title:
        raise TaskError("invalid_task", ["A task needs a title."], status=422)
    if assignee_user_id is not None and not is_eligible(
            db, organization_id=organization_id, user_id=assignee_user_id, permission=required_permission):
        raise TaskError(REASON_ASSIGNEE_NOT_ELIGIBLE,
                        ["The assignee is not an active member who holds the permission this task needs."], status=422)
    approval = request_approval(
        db,
        organization_id=organization_id,
        requester_user_id=requested_by_user_id,
        capability_key=capability_key,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        ttl=due_at - current,
        now=current,
    )
    task = HumanTask(
        organization_id=organization_id,
        kind="approval",
        status=HumanTask.STATUS_PENDING,
        title=clean_title,
        instructions=(instructions or "").strip()[:MAX_INSTRUCTIONS] or None,
        required_permission=required_permission,
        assigned_to_user_id=assignee_user_id,
        requested_by_user_id=requested_by_user_id,
        approval_request_id=approval.id,
        workflow_execution_id=workflow_execution_id,
        workflow_step_id=workflow_step_id,
        due_at=approval.expires_at,
        version=1,
    )
    db.add(task)
    db.flush()
    _event(db, task, event_type="created", actor_id=requested_by_user_id, to_user=assignee_user_id)
    _audit(db, task, actor_id=requested_by_user_id, action="created", metadata={"assigned": assignee_user_id is not None})
    if assignee_user_id is not None:
        _notify(db, task, assignee_user_id)
    return task, True


def assign(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID, assignee_user_id: UUID,
           expected_version: int) -> HumanTask:
    """Assign or reassign a pending task. The new assignee must be an eligible member. A stale version is refused."""
    _require_manage(db, organization_id=organization_id, actor_id=actor_id)
    task = _lock(db, organization_id=organization_id, task_id=task_id)
    if task.status != HumanTask.STATUS_PENDING:
        raise TaskError(REASON_NOT_PENDING)
    if task.version != expected_version:
        raise TaskError(REASON_VERSION_CONFLICT, ["The task changed. Reload and try again."])
    if not is_eligible(db, organization_id=organization_id, user_id=assignee_user_id, permission=task.required_permission):
        raise TaskError(REASON_ASSIGNEE_NOT_ELIGIBLE,
                        ["The assignee is not an active member who holds the permission this task needs."], status=422)
    if assignee_user_id == task.assigned_to_user_id:
        return task
    previous = task.assigned_to_user_id
    event_type = "reassigned" if previous is not None else "assigned"
    task.assigned_to_user_id = assignee_user_id
    task.version += 1
    task.updated_at = datetime.now(UTC)
    db.flush()
    _event(db, task, event_type=event_type, actor_id=actor_id, from_user=previous, to_user=assignee_user_id)
    _audit(db, task, actor_id=actor_id, action=event_type, metadata={})
    _notify(db, task, assignee_user_id)
    return task


def comment(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID, text: str) -> HumanTaskEvent:
    """Add a comment to the task history. Comments can be added by anyone who can see the task, and never change its state."""
    task = _visible_or_404(db, organization_id=organization_id, actor_id=actor_id, task_id=task_id)
    clean = text.strip()
    if not clean or len(clean) > MAX_COMMENT:
        raise TaskError("invalid_comment", ["A comment of 1 to 1000 characters is required."], status=422)
    _event(db, task, event_type="comment", actor_id=actor_id, comment=clean)
    _audit(db, task, actor_id=actor_id, action="comment", metadata={})
    return task


def _visible_or_404(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID) -> HumanTask:
    task = db.scalar(select(HumanTask).where(HumanTask.id == task_id, HumanTask.organization_id == organization_id))
    if task is None or not can_see(db, organization_id=organization_id, actor_id=actor_id, task=task):
        raise TaskError(REASON_NOT_FOUND, status=404)
    return task


def can_see(db: Session, *, organization_id: UUID, actor_id: UUID, task: HumanTask) -> bool:
    """A task is visible to the member who asked for it, its assignee, and any eligible member while it is unassigned."""
    if not _membership_active(db, organization_id=organization_id, user_id=actor_id):
        return False
    if actor_id in (task.requested_by_user_id, task.assigned_to_user_id):
        return True
    return task.assigned_to_user_id is None and actor_permission_granted(
        db, organization_id=organization_id, user_id=actor_id, permission_key=task.required_permission)


def get_task(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID) -> HumanTask:
    return _visible_or_404(db, organization_id=organization_id, actor_id=actor_id, task_id=task_id)


def cancel_for_execution(db: Session, *, organization_id: UUID, workflow_execution_id: UUID, reason: str) -> int:
    """Cancel the pending tasks of a workflow run that is being cancelled. Internal: the run's own cancellation was authorized."""
    rows = db.scalars(select(HumanTask).where(
        HumanTask.organization_id == organization_id,
        HumanTask.workflow_execution_id == workflow_execution_id,
        HumanTask.status == HumanTask.STATUS_PENDING,
    ).with_for_update()).all()
    for task in rows:
        task.status = HumanTask.STATUS_CANCELLED
        task.version += 1
        task.updated_at = datetime.now(UTC)
        db.flush()
        _event(db, task, event_type="cancelled", actor_id=None, comment=reason)
        _audit(db, task, actor_id=task.requested_by_user_id, action="cancelled", metadata={"reason": reason})
    return len(rows)


def list_events(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID) -> list[HumanTaskEvent]:
    _visible_or_404(db, organization_id=organization_id, actor_id=actor_id, task_id=task_id)
    return list(db.scalars(select(HumanTaskEvent).where(
        HumanTaskEvent.organization_id == organization_id,
        HumanTaskEvent.task_id == task_id,
    ).order_by(HumanTaskEvent.created_at, HumanTaskEvent.id)).all())


def list_tasks(db: Session, *, organization_id: UUID, actor_id: UUID, status: str | None = None,
               limit: int = 50) -> list[HumanTask]:
    """Tasks the member may see: their own requests, tasks assigned to them, and unassigned tasks for their permissions."""
    if not _membership_active(db, organization_id=organization_id, user_id=actor_id):
        raise TaskError(REASON_MEMBERSHIP_INACTIVE, status=403)
    rows = db.scalars(select(HumanTask).where(
        HumanTask.organization_id == organization_id,
        *([HumanTask.status == status] if status else []),
    ).order_by(HumanTask.created_at.desc(), HumanTask.id.desc()).limit(500)).all()
    visible = [row for row in rows if can_see(db, organization_id=organization_id, actor_id=actor_id, task=row)]
    return visible[: max(1, min(limit, 100))]


def expire_task(db: Session, task: HumanTask, *, now: datetime) -> None:
    """Expire a pending task whose due time has passed. The governance approval records its own expiry."""
    approval = db.get(ApprovalRequest, task.approval_request_id)
    if approval is not None and approval.status == "pending":
        try:
            # The governance decision marks the approval expired before it refuses, and that refusal is the expected outcome.
            decide_approval(db, organization_id=task.organization_id, approver_user_id=task.requested_by_user_id,
                            approval_id=approval.id, approve=True, now=now)
        except ApprovalError as error:
            if error.reason_code not in (REASON_APPROVAL_EXPIRED,):
                raise
    task.status = HumanTask.STATUS_EXPIRED
    task.version += 1
    task.updated_at = now
    db.flush()
    _event(db, task, event_type="expired", actor_id=None)
    _audit(db, task, actor_id=task.requested_by_user_id, action="expired", metadata={})


def expire_due(db: Session, *, organization_id: UUID, now: datetime | None = None, limit: int = 100) -> list[HumanTask]:
    """Expire pending tasks whose due time has passed. Bounded per call. Returns the expired tasks."""
    moment = now or datetime.now(UTC)
    due = db.scalars(select(HumanTask).where(
        HumanTask.organization_id == organization_id,
        HumanTask.status == HumanTask.STATUS_PENDING,
        HumanTask.due_at <= moment,
    ).order_by(HumanTask.due_at).limit(limit).with_for_update()).all()
    for task in due:
        expire_task(db, task, now=moment)
    return list(due)


def decide(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID, approve: bool,
           comment_text: str | None = None, now: datetime | None = None) -> tuple[HumanTask, bool]:
    """Record the decision. Returns ``(task, changed)``. ``changed`` is False for a repeat of the same decision by the same member.

    An expired task is expired here and the refusal is raised; the caller commits so the expiry persists.
    """
    current = now or datetime.now(UTC)
    task = _lock(db, organization_id=organization_id, task_id=task_id)
    outcome = HumanTask.STATUS_APPROVED if approve else HumanTask.STATUS_REJECTED
    if task.status != HumanTask.STATUS_PENDING:
        if task.status == outcome and task.decided_by_user_id == actor_id:
            return task, False
        raise TaskError(REASON_ALREADY_DECIDED, [f"This task is already {task.status}. The first decision stands."])
    if task.due_at is not None and current >= task.due_at:
        expire_task(db, task, now=current)
        raise TaskError(REASON_EXPIRED, ["The task expired before a decision was made."])
    if not _membership_active(db, organization_id=organization_id, user_id=actor_id):
        raise TaskError(REASON_MEMBERSHIP_INACTIVE, status=403)
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id,
                                    permission_key=task.required_permission):
        raise TaskError(REASON_PERMISSION_DENIED, ["You do not hold the permission this task needs."], status=403)
    if task.assigned_to_user_id is not None and actor_id != task.assigned_to_user_id:
        raise TaskError(REASON_NOT_ASSIGNEE, ["This task is assigned to another member."], status=403)
    if actor_id == task.requested_by_user_id:
        raise TaskError(REASON_SELF_DECISION, ["The member who asked for this decision cannot decide it."], status=403)
    if task.approval_request_id is None:
        raise TaskError(REASON_APPROVAL_MISSING, status=404)
    try:
        decide_approval(db, organization_id=organization_id, approver_user_id=actor_id,
                        approval_id=task.approval_request_id, approve=approve, now=current)
    except ApprovalError as error:
        if error.reason_code == REASON_APPROVAL_EXPIRED:
            expire_task(db, task, now=current)
            raise TaskError(REASON_EXPIRED, ["The task expired before a decision was made."]) from error
        if error.reason_code == REASON_SELF_APPROVAL:
            raise TaskError(REASON_SELF_DECISION, status=403) from error
        if error.reason_code in (REASON_APPROVAL_NOT_PENDING, REASON_APPROVAL_NOT_FOUND):
            raise TaskError(REASON_ALREADY_DECIDED) from error
        raise TaskError(error.reason_code) from error
    task.status = outcome
    task.decided_by_user_id = actor_id
    task.decided_at = current
    task.decision_comment = (comment_text or "").strip()[:MAX_COMMENT] or None
    task.version += 1
    task.updated_at = current
    db.flush()
    _event(db, task, event_type=outcome, actor_id=actor_id, comment=comment_text)
    _audit(db, task, actor_id=actor_id, action=outcome, metadata={})
    return task, True


def cancel(db: Session, *, organization_id: UUID, actor_id: UUID, task_id: UUID, reason: str | None = None) -> HumanTask:
    """Cancel a pending task. Only a member who can manage tasks may cancel, and a decided task is never changed."""
    _require_manage(db, organization_id=organization_id, actor_id=actor_id)
    task = _lock(db, organization_id=organization_id, task_id=task_id)
    if task.status != HumanTask.STATUS_PENDING:
        raise TaskError(REASON_NOT_PENDING)
    task.status = HumanTask.STATUS_CANCELLED
    task.version += 1
    task.updated_at = datetime.now(UTC)
    db.flush()
    _event(db, task, event_type="cancelled", actor_id=actor_id, comment=reason)
    _audit(db, task, actor_id=actor_id, action="cancelled", metadata={})
    return task


__all__ = [
    "TaskError",
    "assign",
    "can_see",
    "cancel",
    "comment",
    "create_task",
    "decide",
    "expire_due",
    "get_task",
    "is_eligible",
    "list_events",
    "list_tasks",
]
