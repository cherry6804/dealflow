"""Workflow runtime and event triggers (DFR1-024): execution, pinning, steps, approvals, delays, events, limits, recovery and tenancy.

The tests use the real database, the real workflow publish path, the real CRM services, the real outbox table and the real agent runtime.
Provider calls go to the scripted boundary the agent tests use. Entitlement and automation switches are set the same way the governance
tests set them. Outbox deliveries are performed by calling the registered handler on the stored event, as the worker does.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.api.workflow_runtime import router as runtime_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.activity import Activity
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.models.outbox_event import OutboxEvent
from app.db.models.workflow import (
    WorkflowDefinition,
    WorkflowLifecycleEvent,
    WorkflowVersion,
)
from app.db.models.workflow_execution import WorkflowExecution, WorkflowExecutionStep
from app.db.session import SessionLocal, get_db_session
from app.governance.entitlement import EntitlementVerdict
from app.governance.service import set_capability_enabled
from app.workflows import runtime, service, triggers
from app.workflows.handlers import handle_execution_requested
from app.workflows.runtime import (
    ExecutionError,
    decide_approval,
    expire_stale_running,
    request_cancel,
    resume_due_timers,
    retry_run,
    start_manual,
)
from tests.agents_support import create_user_in
from tests.test_team_api import TestingSessionLocal, create_owner_manager

MANAGE = ("workflows.read", "workflows.manage", "workflows.publish", "workflows.run", "leads.read", "leads.create",
          "leads.update", "requirements.read", "requirements.update", "contacts.read", "contacts.create", "agents.read",
          "agents.run", "agents.approve", "governance.consent.read")
AUTOMATION_KEYS = ("automation.master", "automation.workflows")


def _cleanup(organization_ids) -> None:
    with SessionLocal() as db:
        db.execute(text_sql("ALTER TABLE workflow_versions DISABLE TRIGGER trg_workflow_versions_immutable"))
        for organization_id in organization_ids:
            for model in (WorkflowExecutionStep, WorkflowExecution, LeadPriorityCorrection, LeadPriorityScore, FollowUp,
                          Activity, Lead, Contact, WorkflowLifecycleEvent, WorkflowVersion, WorkflowDefinition,
                          OutboxEvent, AuditEvent):
                db.execute(delete(model).where(model.organization_id == organization_id))
        db.execute(text_sql("ALTER TABLE workflow_versions ENABLE TRIGGER trg_workflow_versions_immutable"))
        db.commit()


def text_sql(statement: str):
    from sqlalchemy import text
    return text(statement)


@pytest.fixture
def orgs(monkeypatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setattr("app.governance.policy.organization_entitlement_verdict",
                        lambda db, **kwargs: EntitlementVerdict(True, "allowed"))
    owner, org = create_owner_manager(permissions=MANAGE)
    other, other_org = create_owner_manager(permissions=MANAGE)
    editor = create_user_in(org, permissions=MANAGE)
    approver = create_user_in(org, permissions=("workflows.read", "leads.update", "requirements.update"))
    reader = create_user_in(org, permissions=("workflows.read",))
    with SessionLocal() as db:
        for key in AUTOMATION_KEYS:
            set_capability_enabled(db, organization_id=org.id, actor_user_id=owner.id, capability_key=key, is_enabled=True)
        db.commit()
    yield SimpleNamespace(owner=owner, org=org, other=other, other_org=other_org, editor=editor, approver=approver,
                          reader=reader)
    _cleanup((org.id, other_org.id))


# --- helpers ------------------------------------------------------------------------------------------


def config(steps, *, entry=None, inputs=None, outputs=None, limits=None, trigger=None) -> dict:
    return {
        "category": "sales",
        "purpose": "Test workflow.",
        "trigger": trigger or {"type": "manual"},
        "inputs": inputs if inputs is not None else [{"name": "lead_id", "type": "uuid", "required": True}],
        "entry": entry or steps[0]["id"],
        "steps": steps,
        "outputs": outputs or {},
        "limits": limits or {"max_duration_seconds": 600, "max_steps": 10, "max_concurrent_runs": 2, "max_runs_per_hour": 100},
    }


SCORE_STEP = {"id": "score", "type": "crm_action", "action": "lead.calculate_priority",
              "arguments": {"lead_id": "$input.lead_id"}}


def _workflow(orgs, configuration, *, publish=True, name=None, user=None) -> uuid.UUID:
    with SessionLocal() as db:
        row = service.create_workflow(db, organization_id=orgs.org.id, actor_id=(user or orgs.owner).id,
                                      name=name or f"wf-{uuid.uuid4().hex[:8]}", description=None,
                                      configuration=configuration)
        db.commit()
        workflow_id = row.id
    if publish:
        with SessionLocal() as db:
            service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
            db.commit()
    return workflow_id


def _lead(orgs, *, interest: str = "HIGH") -> uuid.UUID:
    with SessionLocal() as db:
        contact = Contact(organization_id=orgs.org.id, first_name="Asha", last_name="Rao", email=f"{uuid.uuid4().hex}@x.test",
                          is_active=True)
        db.add(contact)
        db.flush()
        lead = Lead(organization_id=orgs.org.id, contact_id=contact.id, status="NEW", interest=interest, is_active=True)
        db.add(lead)
        db.commit()
        return lead.id


def _uid(value):
    return value.id if hasattr(value, "id") else value


def _start(orgs, workflow_id, *, inputs=None, key=None, user=None):
    with SessionLocal() as db:
        row, created = start_manual(db, organization_id=orgs.org.id,
                                    user_context=CurrentUserContext(user=_user(_uid(user) or orgs.editor.id)),
                                    workflow_id=workflow_id,
                                    input_values=inputs if inputs is not None else {"lead_id": str(_lead(orgs))},
                                    idempotency_key=key or f"k-{uuid.uuid4().hex}")
        db.commit()
        return row.id, created


def _user(user_id):
    from app.db.models.user import User
    with SessionLocal() as db:
        row = db.get(User, user_id)
        db.expunge(row)
        return row


def _drain(orgs, execution_id) -> None:
    """Deliver the queued execution event, as the outbox worker does, and commit."""
    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent).where(
            OutboxEvent.organization_id == orgs.org.id,
            OutboxEvent.event_type == runtime.EXECUTION_REQUESTED_EVENT,
            OutboxEvent.aggregate_id == str(execution_id),
        ).order_by(OutboxEvent.created_at.desc()))
        if event is not None:
            handle_execution_requested(db, event)
        db.commit()


def _run(orgs, execution_id, *, sleep=lambda seconds: None, between=None):
    """Run from the stored state without the outbox, for tests that need a hook between steps."""
    with SessionLocal() as db:
        execution = db.get(WorkflowExecution, execution_id)
        user = _user(execution.run_as_user_id)
        runtime.run_execution(db, execution, CurrentUserContext(user=user), sleep=sleep, between_steps=between)
        db.commit()


def _row(execution_id) -> WorkflowExecution:
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        db.expunge(row)
        return row


def _steps(execution_id) -> dict[str, WorkflowExecutionStep]:
    with SessionLocal() as db:
        rows = db.scalars(select(WorkflowExecutionStep).where(WorkflowExecutionStep.execution_id == execution_id)).all()
        for row in rows:
            db.expunge(row)
        return {row.step_id: row for row in rows}


def _count_executions(orgs) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(WorkflowExecution.id).where(WorkflowExecution.organization_id == orgs.org.id)).all())


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(runtime_router)

    def session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    client = TestClient(app)
    client.headers["X-Organization-ID"] = str(organization.id)
    return client


# --- manual execution, pinning and step handlers -----------------------------------------------------


def test_a_manual_run_executes_its_crm_step_and_records_it(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)], outputs={"band": "$steps.score.band"}))
    execution_id, created = _start(orgs, workflow_id)
    assert created is True
    assert _row(execution_id).status == "queued"
    _drain(orgs, execution_id)
    row = _row(execution_id)
    assert row.status == "succeeded", row.failure_reason
    steps = _steps(execution_id)
    assert steps["score"].status == "succeeded"
    assert steps["score"].trace["output"]["score_id"]
    assert row.output["band"] in ("high", "medium", "low")
    assert row.trigger_type == "manual"


def test_a_run_stays_pinned_to_the_version_it_started_with(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id,
                             expected_revision=1, name=None, description=None,
                             configuration=config([{"id": "wait", "type": "delay", "seconds": 5}]),
                             description_set=False)
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    assert _row(execution_id).version_number == 1
    _drain(orgs, execution_id)
    assert _row(execution_id).status == "succeeded"
    assert "score" in _steps(execution_id)


def test_the_same_key_with_the_same_input_returns_the_stored_run(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    lead = str(_lead(orgs))
    first, created_first = _start(orgs, workflow_id, inputs={"lead_id": lead}, key="same")
    second, created_second = _start(orgs, workflow_id, inputs={"lead_id": lead}, key="same")
    assert created_first is True and created_second is False and first == second


def test_the_same_key_with_different_input_is_refused(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    _start(orgs, workflow_id, inputs={"lead_id": str(_lead(orgs))}, key="conflict")
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id, inputs={"lead_id": str(_lead(orgs))}, key="conflict")
    assert error.value.reason == "idempotency_conflict"


def test_invalid_input_is_refused_before_anything_is_queued(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    before = _count_executions(orgs)
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id, inputs={"lead_id": "not-an-id"})
    assert error.value.reason == "invalid_input" and error.value.status == 422
    assert _count_executions(orgs) == before


def test_a_paused_or_unpublished_workflow_starts_no_run(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    with SessionLocal() as db:
        service.pause(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    with pytest.raises(ExecutionError) as paused:
        _start(orgs, workflow_id)
    assert paused.value.reason == "workflow_not_runnable"
    draft_only = _workflow(orgs, config([dict(SCORE_STEP, next=None)]), publish=False)
    with pytest.raises(ExecutionError) as no_version:
        _start(orgs, draft_only)
    assert no_version.value.reason == "no_published_version"


def test_disabled_automation_prevents_new_runs(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=orgs.org.id, actor_user_id=orgs.owner.id,
                               capability_key="automation.workflows", is_enabled=False)
        db.commit()
    before = _count_executions(orgs)
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id)
    assert error.value.reason == "workflow_not_runnable"
    assert any("automation" in item.lower() for item in error.value.problems)
    assert _count_executions(orgs) == before


def test_an_unverified_entitlement_prevents_new_runs(orgs, monkeypatch):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    monkeypatch.setattr("app.governance.policy.organization_entitlement_verdict",
                        lambda db, **kwargs: EntitlementVerdict(False, "entitlement_unverified"))
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id)
    assert error.value.reason == "workflow_not_runnable"


def test_a_run_is_refused_when_the_member_lacks_the_crm_permission_its_action_needs(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    reader_with_run = create_user_in(orgs.org, permissions=("workflows.run", "workflows.read"))
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id, user=reader_with_run)
    assert error.value.reason == "workflow_not_runnable"


def test_a_crm_action_is_refused_at_run_time_when_the_permission_is_gone(orgs, monkeypatch):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    from app.agents import crm_actions
    monkeypatch.setattr(crm_actions, "actor_permission_granted", lambda *args, **kwargs: False)
    _drain(orgs, execution_id)
    assert _row(execution_id).status == "stopped"
    assert _row(execution_id).failure_reason == "crm_permission_denied"


def test_a_condition_takes_only_the_matching_branch(orgs):
    steps = [
        {"id": "gate", "type": "condition", "condition": {"left": "$input.track", "operator": "eq", "right": "score"},
         "then": "score", "else": "match"},
        {"id": "score", "type": "crm_action", "action": "lead.calculate_priority",
         "arguments": {"lead_id": "$input.lead_id"}},
        {"id": "match", "type": "crm_action", "action": "matching.evaluate",
         "arguments": {"requirement_id": "$input.lead_id"}},
    ]
    workflow_id = _workflow(orgs, config(steps, inputs=[{"name": "lead_id", "type": "uuid", "required": True},
                                                       {"name": "track", "type": "string", "required": True}]))
    execution_id, _ = _start(orgs, workflow_id, inputs={"lead_id": str(_lead(orgs)), "track": "score"})
    _drain(orgs, execution_id)
    recorded = _steps(execution_id)
    assert recorded["gate"].trace["branch"] == "then"
    assert "score" in recorded and "match" not in recorded
    assert _row(execution_id).status == "succeeded"


def test_an_agent_step_runs_the_agent_runtime_as_the_run_as_member(orgs, monkeypatch):
    workflow_id = _workflow(orgs, config([{"id": "helper", "type": "agent", "agent_id": str(uuid.uuid4()),
                                           "arguments": {"lead_id": "$input.lead_id"}}]), publish=False)
    # The agent reference is not checked here: this case covers the refusal path at run time.
    from app.agents.service import AgentError

    def refuse(*args, **kwargs):
        raise AgentError("not_permitted_now")

    monkeypatch.setattr(runtime, "create_agent_execution", refuse)
    monkeypatch.setattr("app.workflows.publish_checks._agent_problems", lambda *args, **kwargs: [])
    with SessionLocal() as db:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    assert _steps(execution_id)["helper"].status == "failed"
    assert _row(execution_id).failure_reason == "not_permitted_now"


def test_an_agent_budget_refusal_fails_the_step_with_its_reason(orgs, monkeypatch):
    workflow_id = _workflow(orgs, config([{"id": "helper", "type": "agent", "agent_id": str(uuid.uuid4()),
                                           "arguments": {"lead_id": "$input.lead_id"}}]), publish=False)
    from app.agents.service import AgentError

    def budget(*args, **kwargs):
        raise AgentError("budget_exhausted")

    monkeypatch.setattr(runtime, "create_agent_execution", budget)
    monkeypatch.setattr("app.workflows.publish_checks._agent_problems", lambda *args, **kwargs: [])
    with SessionLocal() as db:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    assert _row(execution_id).failure_reason == "budget_exhausted"


# --- approvals, delays and resume ----------------------------------------------------------------------


APPROVAL_FLOW = [
    {"id": "ask", "type": "approval", "approver_permission": "leads.update", "reason": "Confirm the lead.", "next": "score"},
    {"id": "score", "type": "crm_action", "action": "lead.calculate_priority", "arguments": {"lead_id": "$input.lead_id"}},
]


def test_an_approval_pauses_the_run_until_a_different_member_approves(orgs):
    workflow_id = _workflow(orgs, config(APPROVAL_FLOW))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    row = _row(execution_id)
    assert row.status == "waiting_approval" and row.next_step_id == "ask"
    with SessionLocal() as db, pytest.raises(ExecutionError) as own:
        decide_approval(db, organization_id=orgs.org.id,
                        user_context=CurrentUserContext(user=_user(orgs.editor.id)),
                        execution_id=execution_id, step_id="ask", approve=True, reason=None)
    assert own.value.reason == "self_approval_refused"
    with SessionLocal() as db:
        decide_approval(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.approver.id)),
                        execution_id=execution_id, step_id="ask", approve=True, reason="Looks right.")
        db.commit()
    _drain(orgs, execution_id)
    assert _row(execution_id).status == "succeeded"
    assert _steps(execution_id)["ask"].decided_by_user_id == orgs.approver.id


def test_a_rejected_approval_fails_the_run(orgs):
    workflow_id = _workflow(orgs, config(APPROVAL_FLOW))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    with SessionLocal() as db:
        decide_approval(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.approver.id)),
                        execution_id=execution_id, step_id="ask", approve=False, reason="Not now.")
        db.commit()
    row = _row(execution_id)
    assert row.status == "failed" and row.failure_reason == "approval_rejected"


def test_a_member_without_the_approver_permission_cannot_decide(orgs):
    workflow_id = _workflow(orgs, config(APPROVAL_FLOW))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    with SessionLocal() as db, pytest.raises(ExecutionError) as error:
        decide_approval(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.reader.id)),
                        execution_id=execution_id, step_id="ask", approve=True, reason=None)
    assert error.value.status == 403


def test_a_delay_waits_until_its_time_and_the_timer_resumes_the_run(orgs):
    steps = [{"id": "wait", "type": "delay", "seconds": 60, "next": "score"}, dict(SCORE_STEP, next=None)]
    workflow_id = _workflow(orgs, config(steps))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    row = _row(execution_id)
    assert row.status == "waiting_timer" and row.wake_at is not None
    with SessionLocal() as db:
        assert resume_due_timers(db, organization_id=orgs.org.id, now=datetime.now(UTC)) == 0
        db.commit()
    with SessionLocal() as db:
        assert resume_due_timers(db, organization_id=orgs.org.id, now=datetime.now(UTC) + timedelta(seconds=61)) == 1
        db.commit()
    _drain(orgs, execution_id)
    assert _row(execution_id).status == "succeeded"


# --- events, duplicates and loops ----------------------------------------------------------------------


def _event_workflow(orgs) -> uuid.UUID:
    return _workflow(orgs, config([dict(SCORE_STEP, next=None)], trigger={"type": "event", "event": "lead.created"},
                                  inputs=[{"name": "lead_id", "type": "uuid", "required": True}]))


def _deliver_event(orgs, event_type: str, key: str, data: dict | None = None, source=None) -> None:
    with SessionLocal() as db:
        triggers.publish_event(db, organization_id=orgs.org.id, event_type=event_type, event_key=key, data=data or {},
                               source_execution_id=source)
        db.commit()
    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent).where(
            OutboxEvent.organization_id == orgs.org.id,
            OutboxEvent.event_type == triggers.WORKFLOW_EVENT_OUTBOX_TYPE,
            OutboxEvent.aggregate_id == f"{event_type}:{key}",
        ))
        triggers.handle_workflow_event(db, event)
        db.commit()


def test_a_declared_event_starts_the_eligible_workflow_with_the_event_data(orgs):
    _event_workflow(orgs)
    lead = str(_lead(orgs))
    _deliver_event(orgs, "lead.created", lead, {"lead_id": lead})
    with SessionLocal() as db:
        rows = db.scalars(select(WorkflowExecution).where(WorkflowExecution.organization_id == orgs.org.id)).all()
        assert len(rows) == 1
        assert rows[0].trigger_type == "event" and rows[0].trigger_event == "lead.created"
        assert rows[0].input_values == {"lead_id": lead}
        assert rows[0].run_as_user_id == orgs.owner.id


def test_a_duplicate_event_delivery_starts_no_second_run(orgs):
    _event_workflow(orgs)
    lead = str(_lead(orgs))
    _deliver_event(orgs, "lead.created", lead, {"lead_id": lead})
    _deliver_event(orgs, "lead.created", lead, {"lead_id": lead})
    with SessionLocal() as db:
        assert len(db.scalars(select(OutboxEvent.id).where(
            OutboxEvent.organization_id == orgs.org.id,
            OutboxEvent.event_type == triggers.WORKFLOW_EVENT_OUTBOX_TYPE)).all()) == 1
    assert _count_executions(orgs) == 1


def test_an_event_caused_by_a_run_never_starts_another_run(orgs):
    _event_workflow(orgs)
    lead = str(_lead(orgs))
    _deliver_event(orgs, "lead.created", lead, {"lead_id": lead}, source=uuid.uuid4())
    assert _count_executions(orgs) == 0


def test_a_paused_workflow_does_not_start_on_events(orgs):
    workflow_id = _event_workflow(orgs)
    with SessionLocal() as db:
        service.pause(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    lead = str(_lead(orgs))
    _deliver_event(orgs, "lead.created", lead, {"lead_id": lead})
    assert _count_executions(orgs) == 0


def test_an_undeclared_event_type_cannot_be_published(orgs):
    from app.outbox.service import InvalidOutboxEventError
    with SessionLocal() as db, pytest.raises(InvalidOutboxEventError):
        triggers.publish_event(db, organization_id=orgs.org.id, event_type="shell.run", event_key="x")


def test_an_event_from_one_organization_never_starts_another_organizations_workflow(orgs, monkeypatch):
    _event_workflow(orgs)
    lead = str(_lead(orgs))
    _deliver_event(orgs, "lead.created", lead, {"lead_id": lead})
    other = SimpleNamespace(org=orgs.other_org)
    assert _count_executions(other) == 0


def test_the_handler_starts_nothing_for_a_malformed_event(orgs):
    from app.outbox.service import PermanentHandlerError
    with SessionLocal() as db:
        triggers.publish_event(db, organization_id=orgs.org.id, event_type="lead.created", event_key="bad-shape")
        db.commit()
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.organization_id == orgs.org.id,
                                                    OutboxEvent.aggregate_id == "lead.created:bad-shape"))
        event.payload = {"event_type": 5}
        db.flush()
        with pytest.raises(PermanentHandlerError):
            triggers.handle_workflow_event(db, event)


# --- limits, cancellation and recovery ------------------------------------------------------------------


def test_concurrent_runs_are_limited_per_workflow(orgs):
    limits = {"max_duration_seconds": 600, "max_steps": 10, "max_concurrent_runs": 1, "max_runs_per_hour": 100}
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)], limits=limits))
    _start(orgs, workflow_id)
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id)
    assert error.value.reason == "concurrency_limit" and error.value.status == 429


def test_hourly_run_limit_is_enforced(orgs):
    limits = {"max_duration_seconds": 600, "max_steps": 10, "max_concurrent_runs": 5, "max_runs_per_hour": 1}
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)], limits=limits))
    first, _ = _start(orgs, workflow_id)
    _drain(orgs, first)
    with pytest.raises(ExecutionError) as error:
        _start(orgs, workflow_id)
    assert error.value.reason == "rate_limited"


def test_transient_failures_are_retried_a_bounded_number_of_times(orgs, monkeypatch):
    step = dict(SCORE_STEP, next=None, retry={"max_attempts": 3, "backoff_seconds": 1})
    workflow_id = _workflow(orgs, config([step]))
    execution_id, _ = _start(orgs, workflow_id)
    calls = {"n": 0}
    real = runtime.run_crm_action

    def flaky(db, caller, action, arguments):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OperationalError("select", {}, Exception("connection reset"))
        return real(db, caller, action, arguments)

    monkeypatch.setattr(runtime, "run_crm_action", flaky)
    _run(orgs, execution_id)
    assert calls["n"] == 3
    assert _row(execution_id).status == "succeeded"
    assert _steps(execution_id)["score"].attempts == 3


def test_exhausted_transient_failures_dead_letter_the_run(orgs, monkeypatch):
    step = dict(SCORE_STEP, next=None, retry={"max_attempts": 2, "backoff_seconds": 1})
    workflow_id = _workflow(orgs, config([step]))
    execution_id, _ = _start(orgs, workflow_id)

    def always(db, caller, action, arguments):
        raise OperationalError("select", {}, Exception("down"))

    monkeypatch.setattr(runtime, "run_crm_action", always)
    _run(orgs, execution_id)
    row = _row(execution_id)
    assert row.status == "dead_letter" and row.failure_reason == "transient_failure_exhausted"


def test_a_run_past_its_deadline_times_out_at_the_next_boundary(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        row.status = "running"
        row.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        row.started_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    _run(orgs, execution_id)
    assert _row(execution_id).status == "timed_out"


def test_a_queued_run_can_be_cancelled_and_its_event_does_nothing(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        request_cancel(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.editor.id)),
                       execution_id=execution_id)
        db.commit()
    _drain(orgs, execution_id)
    assert _row(execution_id).status == "cancelled"
    assert _steps(execution_id) == {}


def test_a_running_run_is_cancelled_at_its_next_boundary(orgs):
    steps = [dict(SCORE_STEP, next="wait"), {"id": "wait", "type": "delay", "seconds": 5}]
    workflow_id = _workflow(orgs, config(steps))
    execution_id, _ = _start(orgs, workflow_id)

    def cancel_now(db, execution):
        if execution.cancel_requested_at is None and execution.next_step_id == "wait":
            request_cancel(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.editor.id)),
                           execution_id=execution.id)

    _run(orgs, execution_id, between=cancel_now)
    assert _row(execution_id).status == "cancelled"


def test_a_step_interrupted_by_a_restart_fails_instead_of_repeating(orgs, monkeypatch):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        row.status = "running"
        row.started_at = datetime.now(UTC)
        row.deadline_at = datetime.now(UTC) + timedelta(hours=1)
        db.add(WorkflowExecutionStep(organization_id=orgs.org.id, execution_id=execution_id, step_id="score", step_index=0,
                                     step_type="crm_action", status="running", attempts=0))
        db.commit()
    calls = {"n": 0}

    def count(*args, **kwargs):
        calls["n"] += 1
        return "succeeded", None, {"output": {}}

    monkeypatch.setattr(runtime, "run_crm_action", count)
    _run(orgs, execution_id)
    assert calls["n"] == 0
    assert _row(execution_id).failure_reason == "interrupted_step"


def test_a_run_whose_output_is_too_large_fails(orgs, monkeypatch):
    monkeypatch.setattr(runtime, "MAX_OUTPUT_CHARACTERS", 5)
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)], outputs={"band": "$steps.score.band"}))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    assert _row(execution_id).failure_reason == "output_too_large"


def test_stale_running_runs_are_detected_and_expired(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        row.status = "running"
        row.deadline_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()
    with SessionLocal() as db:
        assert expire_stale_running(db, organization_id=orgs.org.id) == 1
        db.commit()
    assert _row(execution_id).status == "timed_out"


def test_a_failed_run_can_be_retried_and_the_original_is_kept(orgs):
    steps = [dict(SCORE_STEP, next=None)]
    workflow_id = _workflow(orgs, config(steps))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        row.status = "failed"
        row.failure_reason = "crm_action_failed"
        db.commit()
    with SessionLocal() as db:
        retried, created = retry_run(db, organization_id=orgs.org.id,
                                     user_context=CurrentUserContext(user=_user(orgs.editor.id)), execution_id=execution_id)
        db.commit()
        assert created is True and retried.retry_of_execution_id == execution_id
        again, created_again = retry_run(db, organization_id=orgs.org.id,
                                         user_context=CurrentUserContext(user=_user(orgs.editor.id)), execution_id=execution_id)
        assert created_again is False and again.id == retried.id
    assert _row(execution_id).status == "failed"


def test_a_succeeded_run_cannot_be_retried(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    with SessionLocal() as db:
        row = db.get(WorkflowExecution, execution_id)
        row.status = "succeeded"
        db.commit()
    with SessionLocal() as db, pytest.raises(ExecutionError) as error:
        retry_run(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.editor.id)),
                  execution_id=execution_id)
    assert error.value.reason == "not_retryable"


# --- revocation, tenancy, audit and the API -----------------------------------------------------------------


def test_a_revoked_membership_stops_a_waiting_run_when_it_resumes(orgs):
    workflow_id = _workflow(orgs, config(APPROVAL_FLOW), user=orgs.owner)
    execution_id, _ = _start(orgs, workflow_id, user=orgs.editor)
    _drain(orgs, execution_id)
    with SessionLocal() as db:
        from app.db.models.membership import Membership
        membership = db.scalar(select(Membership).where(Membership.organization_id == orgs.org.id,
                                                        Membership.user_id == orgs.editor.id))
        membership.is_active = False
        db.commit()
    with SessionLocal() as db:
        decide_approval(db, organization_id=orgs.org.id, user_context=CurrentUserContext(user=_user(orgs.approver.id)),
                        execution_id=execution_id, step_id="ask", approve=True, reason=None)
        db.commit()
    _drain(orgs, execution_id)
    assert _row(execution_id).status == "stopped"
    assert _row(execution_id).failure_reason == "membership_revoked"


def test_another_organization_cannot_read_start_or_cancel_a_run(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    other = _client(orgs.other, orgs.other_org)
    assert other.get(f"/api/v1/automation/executions/{execution_id}").status_code == 404
    assert other.post(f"/api/v1/automation/executions/{execution_id}/cancel").status_code == 404
    assert other.post(f"/api/v1/automation/workflows/{workflow_id}/executions",
                      json={"input": {"lead_id": str(uuid.uuid4())}, "idempotency_key": "x"}).status_code == 404
    assert other.get(f"/api/v1/automation/workflows/{workflow_id}/executions").json()["items"] == []


def test_readers_cannot_start_cancel_or_retry(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    client = _client(orgs.reader, orgs.org)
    assert client.post(f"/api/v1/automation/workflows/{workflow_id}/executions",
                       json={"input": {"lead_id": str(uuid.uuid4())}, "idempotency_key": "r"}).status_code == 403
    assert client.post(f"/api/v1/automation/executions/{execution_id}/retry").status_code == 403
    assert client.get(f"/api/v1/automation/executions/{execution_id}").status_code == 200


def test_runs_and_their_steps_are_audited_without_input_values(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == orgs.org.id,
                                                     AuditEvent.event_type == "workflow_execution")).all()
        actions = {event.action for event in events}
        assert {"workflow.execution.queued", "workflow.execution.started", "workflow.execution.finished"} <= actions


def test_the_api_starts_a_run_and_reports_its_steps_and_failure_reason(orgs):
    workflow_id = _workflow(orgs, config([dict(SCORE_STEP, next=None)]))
    client = _client(orgs.editor, orgs.org)
    lead = str(_lead(orgs))
    created = client.post(f"/api/v1/automation/workflows/{workflow_id}/executions",
                          json={"input": {"lead_id": lead}, "idempotency_key": "api-1"})
    assert created.status_code == 202 and created.json()["created"] is True
    again = client.post(f"/api/v1/automation/workflows/{workflow_id}/executions",
                        json={"input": {"lead_id": lead}, "idempotency_key": "api-1"})
    assert again.status_code == 200 and again.json()["id"] == created.json()["id"]
    execution_id = uuid.UUID(created.json()["id"])
    _drain(orgs, execution_id)
    detail = client.get(f"/api/v1/automation/executions/{execution_id}").json()
    assert detail["status"] == "succeeded"
    assert detail["version_number"] == 1
    assert detail["steps"][0]["step_id"] == "score"
    listed = client.get(f"/api/v1/automation/workflows/{workflow_id}/executions").json()["items"]
    assert listed[0]["id"] == str(execution_id)


def test_the_api_shows_the_pending_approval_and_refuses_an_unknown_field(orgs):
    workflow_id = _workflow(orgs, config(APPROVAL_FLOW))
    execution_id, _ = _start(orgs, workflow_id)
    _drain(orgs, execution_id)
    client = _client(orgs.approver, orgs.org)
    detail = client.get(f"/api/v1/automation/executions/{execution_id}").json()
    assert detail["status"] == "waiting_approval"
    assert detail["pending_approval"]["step_id"] == "ask"
    assert client.post(f"/api/v1/automation/executions/{execution_id}/steps/ask/decision",
                       json={"decision": "approve", "extra": 1}).status_code == 422
    decided = client.post(f"/api/v1/automation/executions/{execution_id}/steps/ask/decision",
                          json={"decision": "approve", "reason": "Fine."})
    assert decided.status_code == 200
