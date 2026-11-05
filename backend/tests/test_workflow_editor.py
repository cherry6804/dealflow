"""Workflow templates and dry-run simulation (DFR1-026).

The tests use the real database, the real publish checks, the real tenant and permission checks and the real audit table. The
simulation is checked for side effects: the CRM runner is replaced by one that fails the test if it is called, and no run, outbox
event, approval task or customer record may be created.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text

from app.api.workflow_editor import router as editor_router
from app.api.workflows import router as workflows_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditEvent
from app.db.models.human_task import HumanTask
from app.db.models.outbox_event import OutboxEvent
from app.db.models.workflow import (
    WorkflowDefinition,
    WorkflowLifecycleEvent,
    WorkflowVersion,
)
from app.db.models.workflow_execution import WorkflowExecution
from app.db.session import SessionLocal, get_db_session
from app.governance.entitlement import EntitlementVerdict
from app.workflows import editor_service, service
from app.workflows.service import WorkflowError
from app.workflows.templates import TEMPLATES, catalogue, template_configuration
from tests.agents_support import create_user_in
from tests.governance_helpers import allow_organization_entitlements
from tests.test_team_api import TestingSessionLocal, create_owner_manager

OWNER_PERMISSIONS = (
    "workflows.read",
    "workflows.manage",
    "workflows.publish",
    "leads.read",
    "leads.update",
)
DRAFTER = ("workflows.read", "workflows.manage")
READER = ("workflows.read",)
LIMITS = {
    "max_steps": 10,
    "max_duration_seconds": 600,
    "max_concurrent_runs": 2,
    "max_runs_per_hour": 100,
}


def _cleanup(organization_ids) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                "ALTER TABLE workflow_versions DISABLE TRIGGER trg_workflow_versions_immutable"
            )
        )
        for organization_id in organization_ids:
            db.execute(
                delete(WorkflowLifecycleEvent).where(
                    WorkflowLifecycleEvent.organization_id == organization_id
                )
            )
            db.execute(
                delete(WorkflowVersion).where(
                    WorkflowVersion.organization_id == organization_id
                )
            )
            db.execute(
                delete(WorkflowDefinition).where(
                    WorkflowDefinition.organization_id == organization_id
                )
            )
            db.execute(
                delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
            )
        db.execute(
            text(
                "ALTER TABLE workflow_versions ENABLE TRIGGER trg_workflow_versions_immutable"
            )
        )
        db.commit()


@pytest.fixture
def orgs(monkeypatch) -> Iterator[SimpleNamespace]:
    allow_organization_entitlements(monkeypatch)
    monkeypatch.setattr(
        "app.governance.policy.organization_entitlement_verdict",
        lambda db, **kwargs: EntitlementVerdict(True, "allowed"),
    )
    owner, org = create_owner_manager(permissions=OWNER_PERMISSIONS)
    other, other_org = create_owner_manager(permissions=OWNER_PERMISSIONS)
    drafter = create_user_in(org, permissions=DRAFTER)
    reader = create_user_in(org, permissions=READER)
    yield SimpleNamespace(
        owner=owner,
        org=org,
        other=other,
        other_org=other_org,
        drafter=drafter,
        reader=reader,
    )
    _cleanup((org.id, other_org.id))


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(workflows_router)
    app.include_router(editor_router)

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


def _from_template(orgs, key: str, *, user=None) -> uuid.UUID:
    with SessionLocal() as db:
        row = editor_service.create_from_template(
            db,
            organization_id=orgs.org.id,
            actor_id=(user or orgs.owner).id,
            template_key=key,
            name=f"{key}-{uuid.uuid4().hex[:8]}",
            description=None,
        )
        db.commit()
        return row.id


def _counts(orgs) -> dict[str, int]:
    with SessionLocal() as db:

        def count(model):
            return db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.organization_id == orgs.org.id)
            )

        return {
            "runs": count(WorkflowExecution),
            "outbox": count(OutboxEvent),
            "tasks": count(HumanTask),
            "versions": count(WorkflowVersion),
        }


def _simulate(client, workflow_id, sample: dict):
    return client.post(
        f"/api/v1/automation/workflows/{workflow_id}/simulate", json={"input": sample}
    )


def _forbid_execution(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("A simulation must never run a CRM action.")

    monkeypatch.setattr("app.agents.crm_actions.run_crm_action", refuse)


def _config_with(steps, *, inputs=None, entry=None) -> dict:
    return {
        "schema_version": "workflow.v1",
        "category": "sales",
        "purpose": "Test workflow.",
        "trigger": {"type": "manual"},
        "inputs": inputs
        if inputs is not None
        else [{"name": "lead_id", "type": "uuid", "required": True}],
        "entry": entry or steps[0]["id"],
        "steps": steps,
        "outputs": {},
        "limits": LIMITS,
    }


def _draft_with(orgs, configuration: dict) -> uuid.UUID:
    with SessionLocal() as db:
        row = service.create_workflow(
            db,
            organization_id=orgs.org.id,
            actor_id=orgs.owner.id,
            name=f"draft-{uuid.uuid4().hex[:8]}",
            description="Test workflow.",
            configuration=configuration,
        )
        db.commit()
        return row.id


# --- catalogue and templates -----------------------------------------------------------------------


def test_the_catalogue_offers_only_choices_the_schema_accepts(orgs):
    response = _client(orgs.reader, orgs.org).get(
        "/api/v1/automation/workflow-templates"
    )
    assert response.status_code == 200
    body = response.json()
    assert "qualification.record" not in body["catalogue"]["crm_actions"]
    assert "approval" in body["catalogue"]["step_types"]
    assert {item["key"] for item in body["items"]} == set(TEMPLATES)
    assert catalogue()["crm_actions"] == body["catalogue"]["crm_actions"]


def test_every_template_is_a_valid_publishable_draft(orgs):
    for key in TEMPLATES:
        workflow_id = _from_template(orgs, key)
        with SessionLocal() as db:
            result = service.validate_draft(
                db,
                organization_id=orgs.org.id,
                actor_id=orgs.owner.id,
                workflow_id=workflow_id,
            )
        assert result["valid"] is True, (key, result["problems"])


def test_a_template_creates_a_draft_only_and_is_audited(orgs):
    before = _counts(orgs)
    response = _client(orgs.owner, orgs.org).post(
        "/api/v1/automation/workflow-templates/new_lead/workflows",
        json={"name": "Lead scoring"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    after = _counts(orgs)
    assert after["versions"] == before["versions"]
    assert after["runs"] == before["runs"] and after["outbox"] == before["outbox"]
    with SessionLocal() as db:
        actions = set(
            db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.organization_id == orgs.org.id
                )
            ).all()
        )
    assert "workflow.created_from_template" in actions


def test_an_unknown_template_is_not_found_and_creates_nothing(orgs):
    before = _counts(orgs)
    response = _client(orgs.owner, orgs.org).post(
        "/api/v1/automation/workflow-templates/missing/workflows",
        json={"name": "Nothing"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "template_not_found"
    assert _counts(orgs) == before


def test_a_reader_cannot_create_from_a_template(orgs):
    response = _client(orgs.reader, orgs.org).post(
        "/api/v1/automation/workflow-templates/new_lead/workflows",
        json={"name": "Blocked"},
    )
    assert response.status_code == 403


def test_a_template_draft_publishes_only_through_the_publish_permission(orgs):
    workflow_id = _from_template(orgs, "follow_up")
    response = _client(orgs.drafter, orgs.org).post(
        f"/api/v1/automation/workflows/{workflow_id}/publish", json={}
    )
    assert response.status_code == 403
    assert _counts(orgs)["versions"] == 0
    response = _client(orgs.owner, orgs.org).post(
        f"/api/v1/automation/workflows/{workflow_id}/publish", json={}
    )
    assert response.status_code in (200, 201)
    assert _counts(orgs)["versions"] == 1


def test_a_template_definition_cannot_be_changed_by_a_caller(orgs):
    original = template_configuration("new_lead")
    original["steps"].clear()
    assert template_configuration("new_lead")["steps"], (
        "the catalogue must not change when a copy is edited"
    )


def test_the_template_catalogue_refuses_a_missing_or_cross_organization_draft(orgs):
    workflow_id = _from_template(orgs, "new_lead")
    response = _client(orgs.other, orgs.other_org).post(
        f"/api/v1/automation/workflows/{workflow_id}/simulate", json={"input": {}}
    )
    assert response.status_code == 404


# --- simulation -------------------------------------------------------------------------------------


def test_simulation_describes_the_path_and_executes_nothing(orgs, monkeypatch):
    _forbid_execution(monkeypatch)
    workflow_id = _from_template(orgs, "new_lead")
    before = _counts(orgs)
    lead_id = str(uuid.uuid4())
    response = _simulate(
        _client(orgs.owner, orgs.org), workflow_id, {"lead_id": lead_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True and body["executed"] is False
    assert [entry["step_id"] for entry in body["plan"]] == ["score_lead"]
    entry = body["plan"][0]
    assert (
        entry["outcome"] == "would_run" and entry["target"] == "lead.calculate_priority"
    )
    assert entry["arguments"]["lead_id"] == {"value": lead_id, "source": "sample input"}
    assert body["not_performed"]
    assert _counts(orgs) == before


def test_an_approval_gate_is_shown_as_waiting_and_the_path_after_it_assumes_approval(
    orgs, monkeypatch
):
    _forbid_execution(monkeypatch)
    workflow_id = _from_template(orgs, "follow_up")
    before = _counts(orgs)
    body = _simulate(
        _client(orgs.owner, orgs.org), workflow_id, {"lead_id": str(uuid.uuid4())}
    ).json()
    assert [entry["outcome"] for entry in body["plan"]] == [
        "would_wait_for_approval",
        "would_run",
    ]
    assert body["plan"][0]["approver_permission"] == "leads.update"
    assert body["plan"][0]["assumes"] == "approval granted"
    assert _counts(orgs) == before and body["executed"] is False


def test_a_condition_is_evaluated_when_its_input_is_known_and_both_branches_are_shown_otherwise(
    orgs, monkeypatch
):
    _forbid_execution(monkeypatch)
    steps = [
        {
            "id": "check",
            "type": "condition",
            "condition": {"left": "$input.flag", "operator": "eq", "right": True},
            "then": "yes",
            "else": "no",
        },
        {"id": "yes", "type": "delay", "seconds": 60},
        {"id": "no", "type": "delay", "seconds": 120},
    ]
    inputs = [{"name": "flag", "type": "boolean", "required": False}]
    workflow_id = _draft_with(orgs, _config_with(steps, inputs=inputs))
    client = _client(orgs.owner, orgs.org)
    taken = _simulate(client, workflow_id, {"flag": True}).json()
    assert [entry["step_id"] for entry in taken["plan"]] == ["check", "yes"]
    assert taken["plan"][0]["outcome"] == "branch_taken"
    unknown = _simulate(client, workflow_id, {}).json()
    assert [entry["step_id"] for entry in unknown["plan"]] == ["check", "yes", "no"]
    assert unknown["plan"][0]["outcome"] == "branch_unknown"


def test_simulation_refuses_an_invalid_draft_and_bad_sample_input(orgs, monkeypatch):
    _forbid_execution(monkeypatch)
    steps = [
        {
            "id": "ask_agent",
            "type": "agent",
            "agent_id": str(uuid.uuid4()),
            "arguments": {},
        }
    ]
    workflow_id = _draft_with(orgs, _config_with(steps))
    client = _client(orgs.owner, orgs.org)
    invalid = _simulate(client, workflow_id, {}).json()
    assert invalid["valid"] is False and invalid["plan"] == []
    assert any(
        "agent" in item["path"] or "agent" in item["message"].lower()
        for item in invalid["problems"]
    )

    template_id = _from_template(orgs, "new_lead")
    undeclared = _simulate(
        client, template_id, {"lead_id": str(uuid.uuid4()), "extra": 1}
    ).json()
    assert undeclared["valid"] is False and undeclared["plan"] == []
    assert any(item["path"] == "input.extra" for item in undeclared["problems"])
    missing = _simulate(client, template_id, {}).json()
    assert any(item["path"] == "input.lead_id" for item in missing["problems"])


def test_a_simulation_is_audited_without_the_input_values(orgs, monkeypatch):
    _forbid_execution(monkeypatch)
    workflow_id = _from_template(orgs, "new_lead")
    secret = str(uuid.uuid4())
    _simulate(_client(orgs.owner, orgs.org), workflow_id, {"lead_id": secret})
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == orgs.org.id,
                AuditEvent.action == "workflow.simulated",
            )
        ).all()
        assert rows
        assert all(secret not in str(row.event_metadata or {}) for row in rows)


# --- saved graphs and publishing ---------------------------------------------------------------------


def test_a_saved_graph_reloads_exactly_including_gates_and_failure_policies(orgs):
    configuration = _config_with(
        [
            {
                "id": "score",
                "type": "crm_action",
                "action": "lead.calculate_priority",
                "arguments": {"lead_id": "$input.lead_id"},
                "timeout_seconds": 120,
                "retry": {"max_attempts": 2, "backoff_seconds": 5},
                "on_failure": {"policy": "route", "route_to": "tell"},
                "approval": {
                    "approver_permission": "leads.update",
                    "expires_after_seconds": 3600,
                },
            },
            {"id": "tell", "type": "delay", "seconds": 30},
        ]
    )
    workflow_id = _draft_with(orgs, configuration)
    client = _client(orgs.owner, orgs.org)
    detail = client.get(f"/api/v1/automation/workflows/{workflow_id}").json()
    saved = copy.deepcopy(detail["draft"])
    response = client.patch(
        f"/api/v1/automation/workflows/{workflow_id}",
        json={"revision": detail["revision"], "configuration": saved},
    )
    assert response.status_code == 200
    reloaded = client.get(f"/api/v1/automation/workflows/{workflow_id}").json()["draft"]
    assert reloaded == saved
    score = reloaded["steps"][0]
    assert score["approval"] == {
        "approver_permission": "leads.update",
        "expires_after_seconds": 3600,
    }
    assert score["on_failure"] == {"policy": "route", "route_to": "tell"}
    assert score["retry"] == {"max_attempts": 2, "backoff_seconds": 5}


def test_an_invalid_flow_cannot_be_published_and_creates_no_version(orgs):
    steps = [
        {
            "id": "ask_agent",
            "type": "agent",
            "agent_id": str(uuid.uuid4()),
            "arguments": {},
        }
    ]
    workflow_id = _draft_with(orgs, _config_with(steps))
    before = _counts(orgs)
    with SessionLocal() as db, pytest.raises(WorkflowError):
        service.publish(
            db,
            organization_id=orgs.org.id,
            actor_id=orgs.owner.id,
            workflow_id=workflow_id,
        )
    assert _counts(orgs)["versions"] == before["versions"]


def test_every_template_survives_a_round_trip_through_the_canonical_schema(orgs):
    from app.workflows.schema import normalise_workflow_configuration

    for key in TEMPLATES:
        once = normalise_workflow_configuration(template_configuration(key))
        assert normalise_workflow_configuration(once) == once, key
