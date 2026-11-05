"""Human tasks and approvals (DFR1-025): gated workflow steps, decisions, expiry, cancellation, tenancy and the append-only history.

The tests use the real database, the real workflow publish path, the real governance approval records and the real outbox table.
Outbox deliveries are performed by calling the registered handler on the stored event, as the worker does. Entitlement is set the way
the workflow tests set it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.api.governance_controls import router as governance_router
from app.api.human_tasks import router as human_tasks_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.approval_request import ApprovalRequest
from app.db.models.human_task import HumanTask, HumanTaskEvent
from app.db.models.lead_priority import LeadPriorityScore
from app.db.models.membership import Membership
from app.db.models.outbox_event import OutboxEvent
from app.db.models.user import User
from app.db.models.workflow_execution import WorkflowExecution, WorkflowExecutionStep
from app.db.session import SessionLocal, get_db_session
from app.governance.entitlement import EntitlementVerdict
from app.governance.service import set_capability_enabled
from app.human_tasks import service as human_tasks
from app.workflows import runtime, service
from app.workflows.handlers import handle_execution_requested
from app.workflows.runtime import (
    ExecutionError,
    cancel_workflow_task,
    decide_approval,
    decide_workflow_task,
    expire_workflow_tasks,
    request_cancel,
    start_manual,
)
from tests.agents_support import create_user_in
from tests.test_team_api import TestingSessionLocal, create_owner_manager
from tests.test_workflow_runtime import _cleanup as _workflow_cleanup

MANAGE = (
    "workflows.read",
    "workflows.manage",
    "workflows.publish",
    "workflows.run",
    "leads.read",
    "leads.create",
    "leads.update",
    "requirements.read",
    "requirements.update",
    "contacts.read",
    "contacts.create",
    "agents.read",
    "agents.run",
    "agents.approve",
    "governance.consent.read",
)
AUTOMATION_KEYS = ("automation.master", "automation.workflows")

GATED_FLOW = [
    {
        "id": "score",
        "type": "crm_action",
        "action": "lead.calculate_priority",
        "arguments": {"lead_id": "$input.lead_id"},
        "approval": {
            "approver_permission": "leads.update",
            "expires_after_seconds": 3600,
        },
    },
]
EXPLICIT_FLOW = [
    {
        "id": "ask",
        "type": "approval",
        "approver_permission": "leads.update",
        "reason": "Confirm the lead.",
        "next": "score",
    },
    {
        "id": "score",
        "type": "crm_action",
        "action": "lead.calculate_priority",
        "arguments": {"lead_id": "$input.lead_id"},
    },
]


def _cleanup(organization_ids) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                "ALTER TABLE human_task_events DISABLE TRIGGER trg_human_task_events_immutable"
            )
        )
        for organization_id in organization_ids:
            db.execute(
                delete(HumanTaskEvent).where(
                    HumanTaskEvent.organization_id == organization_id
                )
            )
            db.execute(
                delete(HumanTask).where(HumanTask.organization_id == organization_id)
            )
        db.execute(
            text(
                "ALTER TABLE human_task_events ENABLE TRIGGER trg_human_task_events_immutable"
            )
        )
        db.commit()
    _workflow_cleanup(organization_ids)


@pytest.fixture
def orgs(monkeypatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setattr(
        "app.governance.policy.organization_entitlement_verdict",
        lambda db, **kwargs: EntitlementVerdict(True, "allowed"),
    )
    owner, org = create_owner_manager(permissions=MANAGE)
    other, other_org = create_owner_manager(permissions=MANAGE)
    editor = create_user_in(org, permissions=MANAGE)
    approver = create_user_in(org, permissions=("leads.update",))
    second_approver = create_user_in(org, permissions=("leads.update",))
    reader = create_user_in(org, permissions=("workflows.read",))
    with SessionLocal() as db:
        for key in AUTOMATION_KEYS:
            set_capability_enabled(
                db,
                organization_id=org.id,
                actor_user_id=owner.id,
                capability_key=key,
                is_enabled=True,
            )
        db.commit()
    yield SimpleNamespace(
        owner=owner,
        org=org,
        other=other,
        other_org=other_org,
        editor=editor,
        approver=approver,
        second_approver=second_approver,
        reader=reader,
    )
    _cleanup((org.id, other_org.id))


# --- helpers ------------------------------------------------------------------------------------------


def config(steps, *, entry=None) -> dict:
    return {
        "category": "sales",
        "purpose": "Test workflow.",
        "trigger": {"type": "manual"},
        "inputs": [{"name": "lead_id", "type": "uuid", "required": True}],
        "entry": entry or steps[0]["id"],
        "steps": steps,
        "outputs": {},
        "limits": {
            "max_duration_seconds": 600,
            "max_steps": 10,
            "max_concurrent_runs": 5,
            "max_runs_per_hour": 100,
        },
    }


def _workflow(orgs, steps) -> uuid.UUID:
    with SessionLocal() as db:
        row = service.create_workflow(
            db,
            organization_id=orgs.org.id,
            actor_id=orgs.owner.id,
            name=f"wf-{uuid.uuid4().hex[:8]}",
            description=None,
            configuration=config(steps),
        )
        db.commit()
        workflow_id = row.id
    with SessionLocal() as db:
        service.publish(
            db,
            organization_id=orgs.org.id,
            actor_id=orgs.owner.id,
            workflow_id=workflow_id,
        )
        db.commit()
    return workflow_id


def _lead(orgs) -> uuid.UUID:
    from app.db.models.contact import Contact
    from app.db.models.lead import Lead

    with SessionLocal() as db:
        contact = Contact(
            organization_id=orgs.org.id,
            first_name="Asha",
            last_name="Rao",
            email=f"{uuid.uuid4().hex}@x.test",
            is_active=True,
        )
        db.add(contact)
        db.flush()
        lead = Lead(
            organization_id=orgs.org.id,
            contact_id=contact.id,
            status="NEW",
            interest="HIGH",
            is_active=True,
        )
        db.add(lead)
        db.commit()
        return lead.id


def _user(user_id: uuid.UUID) -> User:
    with SessionLocal() as db:
        row = db.get(User, user_id)
        db.expunge(row)
        return row


def _start(orgs, workflow_id, *, lead_id=None) -> uuid.UUID:
    with SessionLocal() as db:
        row, _created = start_manual(
            db,
            organization_id=orgs.org.id,
            user_context=CurrentUserContext(user=_user(orgs.editor.id)),
            workflow_id=workflow_id,
            input_values={"lead_id": str(lead_id or _lead(orgs))},
            idempotency_key=f"k-{uuid.uuid4().hex}",
        )
        db.commit()
        return row.id


def _drain(orgs, execution_id) -> None:
    """Deliver the queued execution event, as the outbox worker does, and commit."""
    with SessionLocal() as db:
        event = db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.organization_id == orgs.org.id,
                OutboxEvent.event_type == runtime.EXECUTION_REQUESTED_EVENT,
                OutboxEvent.aggregate_id == str(execution_id),
            )
            .order_by(OutboxEvent.created_at.desc())
        )
        if event is not None:
            handle_execution_requested(db, event)
        db.commit()


def _run(execution_id) -> WorkflowExecution:
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        db.expunge(row)
        return row


def _steps(execution_id) -> dict[str, WorkflowExecutionStep]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(WorkflowExecutionStep).where(
                WorkflowExecutionStep.execution_id == execution_id
            )
        ).all()
        for row in rows:
            db.expunge(row)
        return {row.step_id: row for row in rows}


def _task(execution_id) -> HumanTask:
    with SessionLocal() as db:
        row = db.scalar(
            select(HumanTask).where(HumanTask.workflow_execution_id == execution_id)
        )
        db.expunge(row)
        return row


def _task_by_id(task_id) -> HumanTask:
    with SessionLocal() as db:
        row = db.get(HumanTask, task_id)
        db.expunge(row)
        return row


def _events(task_id) -> list[str]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(HumanTaskEvent)
            .where(HumanTaskEvent.task_id == task_id)
            .order_by(HumanTaskEvent.created_at, HumanTaskEvent.id)
        ).all()
        return [row.event_type for row in rows]


def _decide(
    orgs,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    approve: bool = True,
    comment: str | None = None,
):
    with SessionLocal() as db:
        try:
            task, changed = decide_workflow_task(
                db,
                organization_id=orgs.org.id,
                user_context=CurrentUserContext(user=_user(user_id)),
                task_id=task_id,
                approve=approve,
                comment=comment,
            )
        except ExecutionError as error:
            # As the API does: an expiry is recorded even though the decision is refused.
            if error.reason == human_tasks.REASON_EXPIRED:
                db.commit()
            raise
        db.commit()
        return task.status, changed


def _set_task_due(task_id, due_at: datetime) -> None:
    with SessionLocal() as db:
        approval_id = db.scalar(
            select(HumanTask.approval_request_id).where(HumanTask.id == task_id)
        )
        db.execute(
            update(HumanTask).where(HumanTask.id == task_id).values(due_at=due_at)
        )
        # The approval keeps the task's expiry, and an approval must be requested before it expires.
        db.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == approval_id)
            .values(expires_at=due_at, requested_at=due_at - timedelta(hours=1))
        )
        db.commit()


def _client(user: User, organization, routers) -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router)

    def session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user=user
    )
    client = TestClient(app)
    client.headers["X-Organization-ID"] = str(organization.id)
    return client


def _gated_run(orgs):
    workflow_id = _workflow(orgs, GATED_FLOW)
    lead_id = _lead(orgs)
    execution_id = _start(orgs, workflow_id, lead_id=lead_id)
    _drain(orgs, execution_id)
    return execution_id, lead_id


# --- gated workflow steps -----------------------------------------------------------------------------


def test_a_gated_action_opens_one_task_and_waits_for_a_decision(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    row = _run(execution_id)
    assert (
        row.status == WorkflowExecution.STATUS_WAITING_APPROVAL
        and row.next_step_id == "score"
    )
    task = _task(execution_id)
    assert task.status == HumanTask.STATUS_PENDING
    assert task.required_permission == "leads.update"
    assert task.requested_by_user_id == orgs.editor.id
    assert task.due_at is not None
    assert _events(task.id) == ["created"]
    with SessionLocal() as db:
        count = len(
            db.scalars(
                select(HumanTask.id).where(
                    HumanTask.workflow_execution_id == execution_id
                )
            ).all()
        )
    assert count == 1


def test_an_approval_resumes_the_run_once_and_records_the_decider(orgs):
    execution_id, lead_id = _gated_run(orgs)
    task = _task(execution_id)
    status, changed = _decide(orgs, orgs.approver.id, task.id, comment="Looks right.")
    assert (status, changed) == (HumanTask.STATUS_APPROVED, True)
    _drain(orgs, execution_id)
    row = _run(execution_id)
    assert row.status == WorkflowExecution.STATUS_SUCCEEDED
    assert _steps(execution_id)["score"].status == "succeeded"
    assert _events(task.id) == ["created", "approved"]
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(LeadPriorityScore.id).where(LeadPriorityScore.lead_id == lead_id)
            )
            is not None
        )
        resumes = db.scalars(
            select(OutboxEvent.id).where(
                OutboxEvent.aggregate_id == str(execution_id),
                OutboxEvent.event_type == runtime.EXECUTION_REQUESTED_EVENT,
            )
        ).all()
    assert len(resumes) >= 2, (
        "the resume after the approval is queued under its own key and delivered"
    )


def test_a_repeated_same_decision_changes_nothing_and_a_conflicting_one_is_refused(
    orgs,
):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    assert _decide(orgs, orgs.approver.id, task.id) == (HumanTask.STATUS_APPROVED, True)
    assert _decide(orgs, orgs.approver.id, task.id) == (
        HumanTask.STATUS_APPROVED,
        False,
    )
    with pytest.raises(ExecutionError) as conflict:
        _decide(orgs, orgs.approver.id, task.id, approve=False)
    assert conflict.value.reason == human_tasks.REASON_ALREADY_DECIDED
    assert _task_by_id(task.id).status == HumanTask.STATUS_APPROVED


def test_the_member_who_started_the_run_cannot_decide_its_task(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with pytest.raises(ExecutionError) as refused:
        _decide(orgs, orgs.editor.id, task.id)
    assert refused.value.reason == human_tasks.REASON_SELF_DECISION
    assert refused.value.status == 403
    assert _run(execution_id).status == WorkflowExecution.STATUS_WAITING_APPROVAL


def test_a_member_without_the_task_permission_cannot_decide(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with pytest.raises(ExecutionError) as refused:
        _decide(orgs, orgs.reader.id, task.id)
    assert refused.value.reason == human_tasks.REASON_PERMISSION_DENIED
    assert refused.value.status == 403


def test_a_revoked_member_cannot_decide_even_with_the_permission(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with SessionLocal() as db:
        db.execute(
            update(Membership)
            .where(
                Membership.user_id == orgs.second_approver.id,
                Membership.organization_id == orgs.org.id,
            )
            .values(is_active=False)
        )
        db.commit()
    with pytest.raises(ExecutionError) as refused:
        _decide(orgs, orgs.second_approver.id, task.id)
    assert refused.value.reason == human_tasks.REASON_MEMBERSHIP_INACTIVE
    assert _task_by_id(task.id).status == HumanTask.STATUS_PENDING


def test_a_rejection_ends_the_run_and_the_action_never_runs(orgs):
    execution_id, lead_id = _gated_run(orgs)
    task = _task(execution_id)
    assert _decide(orgs, orgs.approver.id, task.id, approve=False) == (
        HumanTask.STATUS_REJECTED,
        True,
    )
    _drain(orgs, execution_id)
    row = _run(execution_id)
    assert row.status == WorkflowExecution.STATUS_FAILED
    assert row.failure_reason == "approval_rejected"
    assert _steps(execution_id)["score"].status == "failed"
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(LeadPriorityScore.id).where(LeadPriorityScore.lead_id == lead_id)
            )
            is None
        )


def test_a_decision_after_the_due_time_expires_the_task_and_ends_the_run(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    _set_task_due(task.id, datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(ExecutionError) as expired:
        _decide(orgs, orgs.approver.id, task.id)
    assert expired.value.reason == human_tasks.REASON_EXPIRED
    assert _task_by_id(task.id).status == HumanTask.STATUS_EXPIRED
    row = _run(execution_id)
    assert (
        row.status == WorkflowExecution.STATUS_FAILED
        and row.failure_reason == "approval_expired"
    )


def test_the_expiry_sweep_ends_waiting_runs_and_an_expired_task_cannot_resume_them(
    orgs,
):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    _set_task_due(task.id, datetime.now(UTC) - timedelta(minutes=1))
    with SessionLocal() as db:
        assert expire_workflow_tasks(db, organization_id=orgs.org.id) == 1
        db.commit()
    row = _run(execution_id)
    assert (
        row.status == WorkflowExecution.STATUS_FAILED
        and row.failure_reason == "approval_expired"
    )
    with pytest.raises(ExecutionError) as refused:
        _decide(orgs, orgs.approver.id, task.id)
    assert refused.value.reason == human_tasks.REASON_ALREADY_DECIDED
    assert _task_by_id(task.id).status == HumanTask.STATUS_EXPIRED


def test_cancelling_the_run_cancels_its_open_task(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with SessionLocal() as db:
        request_cancel(
            db,
            organization_id=orgs.org.id,
            user_context=CurrentUserContext(user=_user(orgs.editor.id)),
            execution_id=execution_id,
        )
        db.commit()
    assert _task_by_id(task.id).status == HumanTask.STATUS_CANCELLED
    assert _run(execution_id).status == WorkflowExecution.STATUS_CANCELLED


def test_cancelling_the_task_ends_the_run_with_approval_cancelled(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with SessionLocal() as db:
        cancel_workflow_task(
            db,
            organization_id=orgs.org.id,
            user_context=CurrentUserContext(user=_user(orgs.owner.id)),
            task_id=task.id,
            reason="No longer needed.",
        )
        db.commit()
    row = _run(execution_id)
    assert (
        row.status == WorkflowExecution.STATUS_FAILED
        and row.failure_reason == "approval_cancelled"
    )
    assert _task_by_id(task.id).status == HumanTask.STATUS_CANCELLED


def test_a_changed_payload_needs_a_fresh_approval(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    _decide(orgs, orgs.approver.id, task.id)
    with SessionLocal() as db:
        db.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == task.approval_request_id)
            .values(payload_hash="0" * 64)
        )
        db.commit()
    _drain(orgs, execution_id)
    row = _run(execution_id)
    assert (
        row.status == WorkflowExecution.STATUS_FAILED
        and row.failure_reason == "approval_mismatch"
    )
    assert _steps(execution_id)["score"].status == "failed"


def test_an_explicit_approval_step_uses_the_same_task_and_decider_record(orgs):
    workflow_id = _workflow(orgs, EXPLICIT_FLOW)
    execution_id = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    task = _task(execution_id)
    assert task is not None and task.workflow_step_id == "ask"
    _decide(orgs, orgs.approver.id, task.id)
    _drain(orgs, execution_id)
    assert _run(execution_id).status == WorkflowExecution.STATUS_SUCCEEDED
    assert _steps(execution_id)["ask"].decided_by_user_id == orgs.approver.id


def test_a_task_is_decided_through_the_legacy_run_decision_once(orgs):
    workflow_id = _workflow(orgs, EXPLICIT_FLOW)
    execution_id = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    with SessionLocal() as db:
        decide_approval(
            db,
            organization_id=orgs.org.id,
            user_context=CurrentUserContext(user=_user(orgs.approver.id)),
            execution_id=execution_id,
            step_id="ask",
            approve=True,
            reason=None,
        )
        db.commit()
    assert _task(execution_id).status == HumanTask.STATUS_APPROVED


# --- history, tenancy and the HTTP surface -----------------------------------------------------------------


def test_the_task_history_cannot_be_rewritten(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with SessionLocal() as db, pytest.raises(DBAPIError) as changed:
        db.execute(
            text(
                "UPDATE human_task_events SET comment = 'changed' WHERE task_id = :task"
            ),
            {"task": task.id},
        )
        db.commit()
    assert "immutable" in str(changed.value)
    with SessionLocal() as db, pytest.raises(DBAPIError) as removed:
        db.execute(
            text("DELETE FROM human_task_events WHERE task_id = :task"),
            {"task": task.id},
        )
        db.commit()
    assert "immutable" in str(removed.value)


def test_another_organization_cannot_see_or_decide_a_task(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    client = _client(orgs.other, orgs.other_org, [human_tasks_router])
    assert client.get(f"/api/v1/human-tasks/{task.id}").status_code == 404
    response = client.post(
        f"/api/v1/human-tasks/{task.id}/decision", json={"decision": "approve"}
    )
    assert response.status_code == 404
    assert _task_by_id(task.id).status == HumanTask.STATUS_PENDING


def test_the_api_lists_reads_decides_and_comments_with_the_history(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    client = _client(orgs.approver, orgs.org, [human_tasks_router])
    listing = client.get("/api/v1/human-tasks", params={"status": "pending"})
    assert listing.status_code == 200
    assert str(task.id) in [item["id"] for item in listing.json()["items"]]
    detail = client.get(f"/api/v1/human-tasks/{task.id}")
    assert detail.status_code == 200
    assert [event["event_type"] for event in detail.json()["events"]] == ["created"]
    comment = client.post(
        f"/api/v1/human-tasks/{task.id}/comments", json={"text": "Checking the score."}
    )
    assert comment.status_code == 201
    decision = client.post(
        f"/api/v1/human-tasks/{task.id}/decision",
        json={"decision": "approve", "comment": "Fine."},
    )
    assert decision.status_code == 200
    assert (
        decision.json()["status"] == "approved" and decision.json()["changed"] is True
    )
    again = client.post(
        f"/api/v1/human-tasks/{task.id}/decision", json={"decision": "approve"}
    )
    assert again.status_code == 200 and again.json()["changed"] is False
    conflicting = client.post(
        f"/api/v1/human-tasks/{task.id}/decision", json={"decision": "reject"}
    )
    assert (
        conflicting.status_code == 409
        and conflicting.json()["detail"]["reason"] == human_tasks.REASON_ALREADY_DECIDED
    )
    assert _events(task.id) == ["created", "comment", "approved"]


def test_assignment_needs_an_eligible_assignee_a_current_version_and_the_manage_permission(
    orgs,
):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    owner_client = _client(orgs.owner, orgs.org, [human_tasks_router])
    not_eligible = owner_client.post(
        f"/api/v1/human-tasks/{task.id}/assignment",
        json={"assignee_user_id": str(orgs.reader.id), "expected_version": 1},
    )
    assert not_eligible.status_code == 422
    assert (
        not_eligible.json()["detail"]["reason"]
        == human_tasks.REASON_ASSIGNEE_NOT_ELIGIBLE
    )
    assigned = owner_client.post(
        f"/api/v1/human-tasks/{task.id}/assignment",
        json={"assignee_user_id": str(orgs.approver.id), "expected_version": 1},
    )
    assert assigned.status_code == 200 and assigned.json()["version"] == 2
    stale = owner_client.post(
        f"/api/v1/human-tasks/{task.id}/assignment",
        json={"assignee_user_id": str(orgs.approver.id), "expected_version": 1},
    )
    assert (
        stale.status_code == 409
        and stale.json()["detail"]["reason"] == human_tasks.REASON_VERSION_CONFLICT
    )
    editor_client = _client(orgs.editor, orgs.org, [human_tasks_router])
    denied = editor_client.post(
        f"/api/v1/human-tasks/{task.id}/assignment",
        json={"assignee_user_id": str(orgs.approver.id), "expected_version": 2},
    )
    assert denied.status_code == 403
    not_assignee = _client(orgs.second_approver, orgs.org, [human_tasks_router]).post(
        f"/api/v1/human-tasks/{task.id}/decision", json={"decision": "approve"}
    )
    # Once assigned, a task is hidden from other members, so they get the same answer as for a task that does not exist.
    assert not_assignee.status_code == 404
    assert _task_by_id(task.id).status == HumanTask.STATUS_PENDING


def test_the_governance_decision_refuses_an_approval_that_a_task_manages(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    client = _client(orgs.owner, orgs.org, [governance_router])
    response = client.post(
        f"/api/v1/governance/approvals/{task.approval_request_id}/decision",
        json={"approve": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "managed_by_human_task"
    assert _task_by_id(task.id).status == HumanTask.STATUS_PENDING


def test_the_task_is_backed_by_a_governance_approval_for_the_same_expiry(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with SessionLocal() as db:
        approval = db.get(ApprovalRequest, task.approval_request_id)
        assert approval.status == "pending"
        assert approval.requested_by_user_id == orgs.editor.id
        assert approval.capability_key == "automation.workflows"
        assert approval.resource_id == str(execution_id)
        assert approval.expires_at == task.due_at


def test_the_service_refuses_a_decision_by_a_member_who_is_not_the_assignee(orgs):
    execution_id, _lead_id = _gated_run(orgs)
    task = _task(execution_id)
    with SessionLocal() as db:
        human_tasks.assign(
            db,
            organization_id=orgs.org.id,
            actor_id=orgs.owner.id,
            task_id=task.id,
            assignee_user_id=orgs.approver.id,
            expected_version=1,
        )
        db.commit()
    with SessionLocal() as db, pytest.raises(human_tasks.TaskError) as refused:
        human_tasks.decide(
            db,
            organization_id=orgs.org.id,
            actor_id=orgs.second_approver.id,
            task_id=task.id,
            approve=True,
        )
    assert refused.value.reason == human_tasks.REASON_NOT_ASSIGNEE
    assert refused.value.status == 403
    assert _task_by_id(task.id).status == HumanTask.STATUS_PENDING
