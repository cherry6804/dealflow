"""Workflow definitions: the typed schema, the draft and publish lifecycle, immutability, rollback, permissions and tenancy (DFR1-023).

The tests use the real database, the real tenant and permission checks and the real audit table. No workflow is executed: this
story defines and versions workflows, and the runtime is DFR1-024.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.api.workflows import router as workflows_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditEvent
from app.db.models.workflow import (
    WorkflowDefinition,
    WorkflowLifecycleEvent,
    WorkflowVersion,
)
from app.db.session import SessionLocal, get_db_session
from app.governance.entitlement import EntitlementVerdict
from app.workflows import service
from app.workflows.schema import (
    WorkflowValidationError,
    normalise_workflow_configuration,
)
from app.workflows.service import WorkflowError
from tests.agents_support import create_user_in
from tests.governance_helpers import allow_organization_entitlements
from tests.test_team_api import TestingSessionLocal, create_owner_manager

OWNER_PERMISSIONS = ("workflows.read", "workflows.manage", "workflows.publish", "leads.read", "leads.update")
EDITOR = ("workflows.read", "workflows.manage", "workflows.publish", "leads.update")
DRAFTER = ("workflows.read", "workflows.manage")
READER = ("workflows.read",)


def valid_config() -> dict:
    return {
        "category": "sales",
        "purpose": "Score a new lead and ask for a review when it is high priority.",
        "trigger": {"type": "manual"},
        "inputs": [{"name": "lead_id", "type": "uuid", "required": True}],
        "entry": "score",
        "steps": [
            {"id": "score", "type": "crm_action", "action": "lead.calculate_priority",
             "arguments": {"lead_id": "$input.lead_id"}, "next": "gate"},
            {"id": "gate", "type": "condition",
             "condition": {"left": "$steps.score.band", "operator": "eq", "right": "high"},
             "then": "ask", "else": "done"},
            {"id": "ask", "type": "approval", "approver_permission": "leads.update",
             "reason": "Confirm the high priority lead.", "next": "done"},
            {"id": "done", "type": "delay", "seconds": 60},
        ],
        "outputs": {"band": "$steps.score.band"},
        "limits": {"max_duration_seconds": 600, "max_steps": 10, "max_concurrent_runs": 2, "max_runs_per_hour": 100},
        "metadata": {"labels": ["lead"]},
    }


def _cleanup(organization_ids) -> None:
    with SessionLocal() as db:
        # Published versions are immutable. The fixture removes its own test rows with the trigger switched off for this
        # transaction only; no product code path does this.
        db.execute(text("ALTER TABLE workflow_versions DISABLE TRIGGER trg_workflow_versions_immutable"))
        for organization_id in organization_ids:
            db.execute(delete(WorkflowLifecycleEvent).where(WorkflowLifecycleEvent.organization_id == organization_id))
            db.execute(delete(WorkflowVersion).where(WorkflowVersion.organization_id == organization_id))
            db.execute(delete(WorkflowDefinition).where(WorkflowDefinition.organization_id == organization_id))
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.execute(text("ALTER TABLE workflow_versions ENABLE TRIGGER trg_workflow_versions_immutable"))
        db.commit()


@pytest.fixture
def orgs(monkeypatch) -> Iterator[SimpleNamespace]:
    allow_organization_entitlements(monkeypatch)
    monkeypatch.setattr("app.governance.policy.verify_entitlement", lambda *args, **kwargs: EntitlementVerdict(True, "allowed"))
    owner, org = create_owner_manager(permissions=OWNER_PERMISSIONS)
    other, other_org = create_owner_manager(permissions=OWNER_PERMISSIONS)
    editor = create_user_in(org, permissions=EDITOR)
    drafter = create_user_in(org, permissions=DRAFTER)
    reader = create_user_in(org, permissions=READER)
    yield SimpleNamespace(owner=owner, org=org, other=other, other_org=other_org, editor=editor, drafter=drafter,
                          reader=reader)
    _cleanup((org.id, other_org.id))


def _create(orgs, *, name: str | None = None, configuration: dict | None = None, user=None) -> uuid.UUID:
    with SessionLocal() as db:
        row = service.create_workflow(db, organization_id=orgs.org.id, actor_id=(user or orgs.owner).id,
                                      name=name or f"workflow-{uuid.uuid4().hex[:8]}", description="Test workflow.",
                                      configuration=configuration if configuration is not None else valid_config())
        db.commit()
        return row.id


def _publish(orgs, workflow_id, *, user=None):
    with SessionLocal() as db:
        version, created = service.publish(db, organization_id=orgs.org.id, actor_id=(user or orgs.owner).id,
                                           workflow_id=workflow_id)
        db.commit()
        return version.version_number, created


def _row(workflow_id) -> WorkflowDefinition:
    with SessionLocal() as db:
        row = db.get(WorkflowDefinition, workflow_id)
        db.expunge(row)
        return row


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(workflows_router)

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


def _problems(config: dict) -> list[dict[str, str]]:
    with pytest.raises(WorkflowValidationError) as error:
        normalise_workflow_configuration(config)
    return error.value.problems


def _paths(problems) -> set[str]:
    return {item["path"] for item in problems}


# --- schema: valid definitions and rejected ones --------------------------------------------------


def test_a_complete_definition_is_accepted_and_canonicalised():
    canonical = normalise_workflow_configuration(valid_config())
    assert canonical["schema_version"] == "workflow.v1"
    assert canonical["entry"] == "score"
    assert [step["id"] for step in canonical["steps"]] == ["score", "gate", "ask", "done"]
    assert canonical["steps"][0]["on_failure"] == {"policy": "stop", "route_to": None}


def test_an_unknown_field_is_rejected_at_every_level():
    config = valid_config()
    config["extra"] = True
    assert "configuration" in _paths(_problems(config))

    config = valid_config()
    config["steps"][0]["script"] = "print(1)"
    assert "steps[0]" in _paths(_problems(config))

    config = valid_config()
    config["steps"][1]["condition"]["expression"] = "x > 1"
    assert "steps[1].condition" in _paths(_problems(config))

    config = valid_config()
    config["steps"][0]["retry"] = {"max_attempts": 2, "backoff_seconds": 1, "jitter": True}
    assert "steps[0].retry" in _paths(_problems(config))


def test_a_branch_to_a_missing_step_is_rejected():
    config = valid_config()
    config["steps"][1]["then"] = "nowhere"
    assert "steps.gate.then" in _paths(_problems(config))


def test_a_cycle_is_rejected():
    config = valid_config()
    config["steps"][3]["next"] = "score"
    problems = _problems(config)
    assert any("cycle" in item["message"] for item in problems)


def test_an_unreachable_step_is_rejected():
    config = valid_config()
    config["steps"].append({"id": "orphan", "type": "delay", "seconds": 5})
    assert "steps.orphan" in _paths(_problems(config))


def test_a_reference_to_a_later_step_is_rejected():
    config = valid_config()
    config["steps"][0]["arguments"] = {"lead_id": "$input.lead_id"}
    config["steps"][1]["condition"]["left"] = "$steps.done.seconds"
    assert "steps.gate.condition.left" in _paths(_problems(config))


def test_a_reference_to_a_field_the_step_does_not_output_is_rejected():
    config = valid_config()
    config["steps"][1]["condition"]["left"] = "$steps.score.not_a_field"
    assert "steps.gate.condition.left" in _paths(_problems(config))


def test_a_reference_to_an_undeclared_input_is_rejected():
    config = valid_config()
    config["steps"][0]["arguments"] = {"lead_id": "$input.other"}
    assert "steps[0].arguments.lead_id" in _paths(_problems(config))


def test_a_literal_value_where_a_reference_is_required_is_rejected():
    config = valid_config()
    config["steps"][0]["arguments"] = {"lead_id": "00000000-0000-0000-0000-000000000000"}
    assert "steps[0].arguments.lead_id" in _paths(_problems(config))


def test_a_crm_action_outside_the_catalogue_is_rejected():
    config = valid_config()
    config["steps"][0]["action"] = "contacts.delete"
    assert "steps[0].action" in _paths(_problems(config))


def test_a_crm_action_missing_a_required_argument_is_rejected():
    config = valid_config()
    config["steps"][0]["arguments"] = {}
    assert any("Missing required argument" in item["message"] for item in _problems(config))


def test_an_approval_without_a_reason_is_rejected():
    config = valid_config()
    del config["steps"][2]["reason"]
    assert any("reason" in item["path"] for item in _problems(config))


def test_a_delay_without_seconds_or_with_retries_is_rejected():
    config = valid_config()
    del config["steps"][3]["seconds"]
    assert "steps[3].seconds" in _paths(_problems(config))
    config = valid_config()
    config["steps"][3]["retry"] = {"max_attempts": 2, "backoff_seconds": 1}
    assert "steps[3].retry" in _paths(_problems(config))


def test_a_condition_cannot_be_retried_or_have_a_next_step():
    config = valid_config()
    config["steps"][1]["retry"] = {"max_attempts": 2, "backoff_seconds": 1}
    assert "steps[1]" in _paths(_problems(config))


def test_executable_or_unrestricted_expressions_are_refused():
    config = valid_config()
    config["steps"][1]["condition"]["operator"] = "eval"
    assert "steps[1].condition.operator" in _paths(_problems(config))
    config = valid_config()
    config["steps"][1]["condition"]["right"] = {"code": "__import__('os')"}
    assert "steps[1].condition.right" in _paths(_problems(config))


def test_only_manual_or_declared_events_may_trigger():
    config = valid_config()
    config["trigger"] = {"type": "event", "event": "lead.created"}
    assert normalise_workflow_configuration(config)["trigger"] == {"type": "event", "event": "lead.created"}
    config["trigger"] = {"type": "event", "event": "shell.run"}
    assert "trigger.event" in _paths(_problems(config))
    config["trigger"] = {"type": "manual", "event": "lead.created"}
    assert "trigger" in _paths(_problems(config))


def test_limits_are_bounded_and_the_step_count_is_capped():
    config = valid_config()
    config["limits"]["max_duration_seconds"] = 10**9
    assert "limits.max_duration_seconds" in _paths(_problems(config))
    config = valid_config()
    config["limits"]["max_steps"] = 2
    assert "limits.max_steps" in _paths(_problems(config))


def test_a_draft_without_steps_is_valid_but_cannot_be_published():
    draft = normalise_workflow_configuration({"purpose": "Later."})
    assert draft["steps"] == []
    problems = service.require_publishable(draft, name="Draft")
    assert {item["path"] for item in problems} >= {"category", "steps", "limits"}


def test_the_schema_version_must_match():
    config = valid_config()
    config["schema_version"] = "workflow.v9"
    assert "schema_version" in _paths(_problems(config))


# --- lifecycle: drafts, publishing and immutability ---------------------------------------------------


def test_a_draft_is_created_and_edited_with_a_revision_check(orgs):
    workflow_id = _create(orgs)
    with SessionLocal() as db:
        row = service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                                   expected_revision=1, name=None, description=None,
                                   configuration={**valid_config(), "purpose": "A new purpose for this draft."},
                                   description_set=False)
        db.commit()
        assert row.draft_revision == 2
    with SessionLocal() as db, pytest.raises(WorkflowError) as stale:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                             expected_revision=1, name=None, description=None, configuration=valid_config(),
                             description_set=False)
    assert stale.value.reason == "revision_conflict"


def test_an_invalid_draft_edit_is_refused_and_nothing_changes(orgs):
    workflow_id = _create(orgs)
    bad = valid_config()
    bad["steps"][0]["action"] = "contacts.delete"
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                             expected_revision=1, name=None, description=None, configuration=bad, description_set=False)
    assert error.value.reason == "invalid_configuration" and error.value.status == 422
    assert _row(workflow_id).draft_revision == 1


def test_publishing_creates_an_immutable_version_and_an_unchanged_draft_publishes_nothing_new(orgs):
    workflow_id = _create(orgs)
    number, created = _publish(orgs, workflow_id)
    assert (number, created) == (1, True)
    assert _publish(orgs, workflow_id) == (1, False)
    row = _row(workflow_id)
    assert row.status == "published" and row.current_version_id is not None


def test_editing_the_draft_never_changes_the_published_version(orgs):
    workflow_id = _create(orgs)
    _publish(orgs, workflow_id)
    with SessionLocal() as db:
        version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id))
        before = (version.configuration, version.content_hash)
    with SessionLocal() as db:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                             expected_revision=1, name=None, description=None,
                             configuration={**valid_config(), "purpose": "A changed purpose for the draft only."},
                             description_set=False)
        db.commit()
    with SessionLocal() as db:
        version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id))
        assert (version.configuration, version.content_hash) == before
        assert service.has_unpublished_changes(db, db.get(WorkflowDefinition, workflow_id)) is True


def test_the_database_refuses_to_update_or_delete_a_published_version(orgs):
    workflow_id = _create(orgs)
    _publish(orgs, workflow_id)
    with SessionLocal() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE workflow_versions SET name = 'changed' WHERE workflow_id = :id"), {"id": workflow_id})
        db.rollback()
    with SessionLocal() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("DELETE FROM workflow_versions WHERE workflow_id = :id"), {"id": workflow_id})
        db.rollback()


def test_a_publisher_who_lacks_the_action_permission_cannot_publish(orgs):
    workflow_id = _create(orgs)
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.drafter.id, workflow_id=workflow_id)
    assert error.value.reason == "permission_denied"
    drafter_view = _client(orgs.drafter, orgs.org).post(f"/api/v1/automation/workflows/{workflow_id}/publish")
    assert drafter_view.status_code == 403


def test_publishing_is_refused_when_an_action_permission_is_missing_for_the_publisher(orgs):
    workflow_id = _create(orgs)
    limited = create_user_in(orgs.org, permissions=("workflows.read", "workflows.manage", "workflows.publish"))
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.publish(db, organization_id=orgs.org.id, actor_id=limited.id, workflow_id=workflow_id)
    assert error.value.reason == "publish_blocked"
    assert any("leads.update" in item["message"] or "permission" in item["message"] for item in error.value.problems)


def test_publishing_fails_closed_when_the_entitlement_cannot_be_verified(orgs, monkeypatch):
    workflow_id = _create(orgs)
    monkeypatch.setattr("app.governance.policy.verify_entitlement",
                        lambda *args, **kwargs: EntitlementVerdict(False, "entitlement_unverified"))
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert error.value.reason == "publish_blocked"
    assert any(item["path"] == "entitlement" for item in error.value.problems)


def test_publishing_refuses_an_agent_reference_that_does_not_exist_in_the_organization(orgs):
    config = {
        "category": "operations",
        "purpose": "Run a helper agent.",
        "inputs": [{"name": "lead_id", "type": "uuid", "required": True}],
        "entry": "helper",
        "steps": [
            {"id": "helper", "type": "agent", "agent_id": str(uuid.uuid4()),
             "arguments": {"lead_id": "$input.lead_id"}, "next": "done"},
            {"id": "done", "type": "delay", "seconds": 5},
        ],
        "limits": {"max_duration_seconds": 600, "max_steps": 10, "max_concurrent_runs": 1, "max_runs_per_hour": 10},
    }
    workflow_id = _create(orgs, configuration=config)
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert error.value.reason == "publish_blocked"
    assert any("does not exist" in item["message"] for item in error.value.problems)


def test_a_draft_cannot_be_published_while_incomplete(orgs):
    workflow_id = _create(orgs, configuration={"purpose": "Not yet."})
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert error.value.reason == "publish_blocked"
    assert "steps" in _paths(error.value.problems)


def test_validation_reports_problems_without_changing_anything(orgs):
    workflow_id = _create(orgs, configuration={"purpose": "Not yet."})
    with SessionLocal() as db:
        result = service.validate_draft(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert result["valid"] is False and result["problems"]
    assert _row(workflow_id).status == "draft"


# --- rollback, pause, resume and archive ---------------------------------------------------------------


def _two_versions(orgs) -> uuid.UUID:
    workflow_id = _create(orgs)
    _publish(orgs, workflow_id)
    with SessionLocal() as db:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                             expected_revision=1, name=None, description=None,
                             configuration={**valid_config(), "purpose": "The second published purpose."},
                             description_set=False)
        db.commit()
    _publish(orgs, workflow_id)
    return workflow_id


def test_rollback_points_at_an_earlier_immutable_version_without_creating_one(orgs):
    workflow_id = _two_versions(orgs)
    with SessionLocal() as db:
        versions_before = len(db.scalars(select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id)).all())
        first = db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id,
                                                        WorkflowVersion.version_number == 1))
        first_hash = first.content_hash
    with SessionLocal() as db:
        row = service.rollback(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id,
                               version_number=1)
        db.commit()
        assert row.current_version_id is not None
    with SessionLocal() as db:
        assert len(db.scalars(select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id)).all()) == versions_before
        assert db.get(WorkflowVersion, _row(workflow_id).current_version_id).content_hash == first_hash
        events = db.scalars(select(WorkflowLifecycleEvent.action).where(WorkflowLifecycleEvent.workflow_id == workflow_id)).all()
        assert "rolled_back" in events


def test_rollback_to_the_current_or_a_missing_version_is_refused(orgs):
    workflow_id = _two_versions(orgs)
    with SessionLocal() as db, pytest.raises(WorkflowError) as current:
        service.rollback(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id, version_number=2)
    assert current.value.reason == "invalid_rollback_target"
    with SessionLocal() as db, pytest.raises(WorkflowError) as missing:
        service.rollback(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id, version_number=9)
    assert missing.value.reason == "version_not_found"


def test_rollback_needs_the_publish_permission(orgs):
    workflow_id = _two_versions(orgs)
    client = _client(orgs.drafter, orgs.org)
    response = client.post(f"/api/v1/automation/workflows/{workflow_id}/rollback", json={"version_number": 1})
    assert response.status_code == 403


def test_pause_and_resume_change_the_status_and_are_checked_again_on_resume(orgs, monkeypatch):
    workflow_id = _two_versions(orgs)
    with SessionLocal() as db:
        service.pause(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id, reason="Review.")
        db.commit()
    assert _row(workflow_id).status == "paused"
    monkeypatch.setattr("app.governance.policy.verify_entitlement",
                        lambda *args, **kwargs: EntitlementVerdict(False, "entitlement_unverified"))
    with SessionLocal() as db, pytest.raises(WorkflowError) as blocked:
        service.resume(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert blocked.value.reason == "publish_blocked"
    assert _row(workflow_id).status == "paused"
    monkeypatch.setattr("app.governance.policy.verify_entitlement",
                        lambda *args, **kwargs: EntitlementVerdict(True, "allowed"))
    with SessionLocal() as db:
        service.resume(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    assert _row(workflow_id).status == "published"


def test_a_new_version_published_while_paused_stays_paused(orgs):
    workflow_id = _two_versions(orgs)
    with SessionLocal() as db:
        service.pause(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    with SessionLocal() as db:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                             expected_revision=2, name=None, description=None,
                             configuration={**valid_config(), "purpose": "A third version while paused."},
                             description_set=False)
        db.commit()
    _publish(orgs, workflow_id)
    assert _row(workflow_id).status == "paused"


def test_pausing_a_draft_is_refused(orgs):
    workflow_id = _create(orgs)
    with SessionLocal() as db, pytest.raises(WorkflowError) as error:
        service.pause(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert error.value.reason == "invalid_state"


def test_an_archived_workflow_cannot_be_edited_or_published(orgs):
    workflow_id = _create(orgs)
    _publish(orgs, workflow_id)
    with SessionLocal() as db:
        service.archive(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    assert _row(workflow_id).status == "archived"
    with SessionLocal() as db, pytest.raises(WorkflowError) as edit:
        service.update_draft(db, organization_id=orgs.org.id, actor_id=orgs.editor.id, workflow_id=workflow_id,
                             expected_revision=1, name=None, description=None, configuration=valid_config(),
                             description_set=False)
    assert edit.value.reason == "workflow_archived"
    with SessionLocal() as db, pytest.raises(WorkflowError) as publish_error:
        service.publish(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
    assert publish_error.value.reason == "workflow_archived"


def test_the_history_records_every_transition_in_order(orgs):
    workflow_id = _two_versions(orgs)
    with SessionLocal() as db:
        service.pause(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        db.commit()
    with SessionLocal() as db:
        history = service.list_history(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, workflow_id=workflow_id)
        actions = [event.action for event in history]
    assert actions == ["created", "published", "draft_saved", "published", "paused"]


def test_a_name_is_unique_within_an_organization_only(orgs):
    _create(orgs, name="Lead follow-up")
    with SessionLocal() as db, pytest.raises(WorkflowError) as duplicate:
        service.create_workflow(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, name="Lead follow-up",
                                description=None, configuration=valid_config())
    assert duplicate.value.reason == "workflow_name_taken"
    with SessionLocal() as db:
        service.create_workflow(db, organization_id=orgs.other_org.id, actor_id=orgs.other.id, name="Lead follow-up",
                                description=None, configuration=valid_config())
        db.commit()


# --- permissions, tenancy and the API -----------------------------------------------------------------


def test_readers_can_read_but_not_draft_or_publish(orgs):
    workflow_id = _create(orgs)
    client = _client(orgs.reader, orgs.org)
    assert client.get("/api/v1/automation/workflows").status_code == 200
    assert client.get(f"/api/v1/automation/workflows/{workflow_id}").status_code == 200
    assert client.post("/api/v1/automation/workflows", json={"name": "x"}).status_code == 403
    assert client.post(f"/api/v1/automation/workflows/{workflow_id}/publish").status_code == 403


def test_a_drafter_without_the_publish_permission_cannot_publish_pause_or_archive(orgs):
    workflow_id = _create(orgs)
    client = _client(orgs.drafter, orgs.org)
    assert client.post(f"/api/v1/automation/workflows/{workflow_id}/publish").status_code == 403
    assert client.post(f"/api/v1/automation/workflows/{workflow_id}/archive").status_code == 403
    assert client.post(f"/api/v1/automation/workflows/{workflow_id}/validate").status_code == 200


def test_another_organization_cannot_see_edit_publish_or_list_these_workflows(orgs):
    workflow_id = _create(orgs)
    other = _client(orgs.other, orgs.other_org)
    assert other.get("/api/v1/automation/workflows").json()["items"] == []
    assert other.get(f"/api/v1/automation/workflows/{workflow_id}").status_code == 404
    assert other.patch(f"/api/v1/automation/workflows/{workflow_id}",
                       json={"revision": 1, "name": "taken over"}).status_code == 404
    assert other.post(f"/api/v1/automation/workflows/{workflow_id}/publish").status_code == 404
    assert other.get(f"/api/v1/automation/workflows/{workflow_id}/history").status_code == 404


def test_the_api_refuses_unknown_fields_and_returns_problem_paths(orgs):
    client = _client(orgs.editor, orgs.org)
    workflow_id = _create(orgs)
    response = client.patch(f"/api/v1/automation/workflows/{workflow_id}", json={"revision": 1, "owner": "me"})
    assert response.status_code == 422
    bad = copy.deepcopy(valid_config())
    bad["steps"][0]["action"] = "contacts.delete"
    response = client.patch(f"/api/v1/automation/workflows/{workflow_id}", json={"revision": 1, "configuration": bad})
    assert response.status_code == 422
    assert any(item["path"] == "steps[0].action" for item in response.json()["detail"]["problems"])


def test_the_api_publishes_and_reports_the_version(orgs):
    client = _client(orgs.owner, orgs.org)
    workflow_id = _create(orgs)
    first = client.post(f"/api/v1/automation/workflows/{workflow_id}/publish")
    assert first.status_code == 201
    assert first.json()["version_number"] == 1
    assert first.json()["required_permissions"] == ["leads.update"]
    again = client.post(f"/api/v1/automation/workflows/{workflow_id}/publish")
    assert again.status_code == 200 and again.json()["created"] is False


def test_lifecycle_events_are_audited_without_the_configuration_body(orgs):
    workflow_id = _two_versions(orgs)
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == orgs.org.id,
                                                     AuditEvent.event_type == "workflow")).all()
        actions = {event.action for event in events}
        assert {"workflow.created", "workflow.published"} <= actions
        assert all("The second published purpose" not in (event.event_metadata or "") for event in events)
    assert _row(workflow_id).status == "published"
