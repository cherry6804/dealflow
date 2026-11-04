"""Agent definitions, validation, versioning, rollback, pause, resume and archive (DFR1-019)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.agents.configuration import ConfigurationError, normalise_configuration
from app.agents.service import (
    AgentError,
    archive,
    create_agent,
    list_versions,
    pause,
    preview,
    publish,
    resume,
    rollback,
    update_draft,
)
from app.ai_tools import service as tool_service
from app.api.agents import router as agents_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.agent import AgentVersion
from app.db.models.document import Document
from app.db.session import SessionLocal, get_db_session
from app.governance.service import set_capability_enabled
from tests.agents_support import (
    agent_row,
    config,
    create_draft,
    create_user_in,
)
from tests.agents_support import publish as publish_version
from tests.test_team_api import TestingSessionLocal

REGISTERED = frozenset({"contacts.get", "leads.get", "requirements.get", "properties.get", "deals.get"})


def _normalise(raw):
    return normalise_configuration(raw, registered_tools=REGISTERED)


# --- configuration validation (pure) ----------------------------------------------------------------


def test_a_valid_configuration_is_normalised_to_its_canonical_shape():
    canonical = _normalise(config())
    assert canonical["trigger"] == {"type": "manual"}
    assert [step["kind"] for step in canonical["steps"]] == ["tool", "model"]
    assert canonical["tools"] == ["contacts.get"]


@pytest.mark.parametrize("mutation, message", [
    ({"unexpected": 1}, "unknown field"),
    ({"tools": ["deals.delete"]}, "approved registry"),
    ({"trigger": {"type": "webhook"}}, "manual"),
    ({"autonomy_level": "free"}, "autonomy_level"),
    ({"limits": {"max_steps": 500}}, "between 1 and 20"),
    ({"limits": {"max_tool_calls": 1, "unknown_limit": 3}}, "unknown field"),
    ({"steps": []}, "non-empty"),
    ({"inputs": [{"name": "Bad Name", "type": "uuid"}]}, "lower case"),
])
def test_invalid_configurations_are_refused_with_named_problems(mutation, message):
    raw = config()
    raw.update(mutation)
    with pytest.raises(ConfigurationError) as refused:
        _normalise(raw)
    assert any(message in problem for problem in refused.value.problems)


def test_a_tool_step_must_name_an_assigned_tool_and_a_declared_input():
    raw = config(steps=[{"kind": "tool", "tool": "leads.get", "arguments": {"lead_id": "$input.lead"}}])
    with pytest.raises(ConfigurationError) as refused:
        _normalise(raw)
    assert any("not assigned" in problem for problem in refused.value.problems)
    raw = config(steps=[{"kind": "tool", "tool": "contacts.get", "arguments": {"contact_id": "$input.missing"}}])
    with pytest.raises(ConfigurationError) as refused:
        _normalise(raw)
    assert any("undeclared input" in problem for problem in refused.value.problems)


def test_a_suggest_only_agent_needs_a_human_gate_and_knowledge_steps_need_sources():
    raw = config(approval_policy="none", autonomy_level="suggest")
    with pytest.raises(ConfigurationError) as refused:
        _normalise(raw)
    assert any("suggest-only" in problem for problem in refused.value.problems)
    raw = config(steps=[{"kind": "knowledge", "query": "pricing", "top_k": 3}])
    with pytest.raises(ConfigurationError) as refused:
        _normalise(raw)
    assert any("knowledge source" in problem for problem in refused.value.problems)


def test_a_model_prompt_may_only_refer_to_earlier_steps():
    raw = config(steps=[{"kind": "model", "prompt": "Use $step.0 now.", "output_schema": {"text": "string"}}])
    with pytest.raises(ConfigurationError) as refused:
        _normalise(raw)
    assert any("does not come before" in problem for problem in refused.value.problems)


# --- drafts, tenant isolation and permissions ----------------------------------------------------------


def test_editing_a_draft_leaves_the_published_version_unchanged(world):
    draft = create_draft(world)
    version = publish_version(world, draft["id"])
    with TestingSessionLocal() as db:
        update_draft(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"],
                     configuration=config(purpose="A different purpose."))
        db.commit()
    with SessionLocal() as db:
        stored = db.get(AgentVersion, version.id)
        assert stored.configuration["purpose"] == "Summarise a contact for a salesperson."


def _session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def test_another_organization_cannot_read_or_change_an_agent(world):
    draft = create_draft(world)
    app = FastAPI()
    app.include_router(agents_router)
    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=world.other)
    with TestClient(app) as client:
        client.headers["X-Organization-ID"] = str(world.other_org.id)
        assert client.get(f"/api/v1/agents/{draft['id']}").status_code == 404
        assert client.patch(f"/api/v1/agents/{draft['id']}", json={"name": "x"}).status_code == 404
        assert client.post(f"/api/v1/agents/{draft['id']}/publish").status_code == 404


def test_a_member_without_the_manage_permission_cannot_create_a_draft(world):
    reader = create_user_in(world.org, permissions=("agents.read",))
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
        create_agent(db, organization_id=world.org.id, actor_id=reader.id, name="nope",
                     description=None, configuration=config())
    assert refused.value.reason == "permission_denied"


def test_a_publisher_without_the_publish_permission_is_refused(world):
    draft = create_draft(world)
    member = create_user_in(world.org, permissions=("agents.read", "agents.manage"))
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            publish(db, organization_id=world.org.id, actor_id=member.id, agent_id=draft["id"])
    assert refused.value.reason == "permission_denied"


# --- publishing, versions and rollback ------------------------------------------------------------------


def test_publishing_freezes_a_numbered_version_with_its_validation_snapshot(world):
    draft = create_draft(world)
    version = publish_version(world, draft["id"])
    assert version.version_number == 1
    assert version.validation_snapshot["limits"]["max_steps"] == 5
    assert agent_row(draft["id"]).current_version_id == version.id


def test_publishing_refuses_a_configuration_without_every_limit(world):
    limits = dict(config()["limits"])
    limits.pop("max_retries")
    draft = create_draft(world, cfg=config(limits=limits))
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            publish(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
    assert refused.value.reason == "publish_blocked"
    assert any("max_retries" in problem for problem in refused.value.problems)
    assert agent_row(draft["id"]).current_version_id is None


def test_publishing_is_refused_when_the_ai_capability_is_disabled(world):
    draft = create_draft(world)
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=world.org.id, actor_user_id=world.owner.id,
                               capability_key="ai.agents", is_enabled=False)
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            publish(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
    assert refused.value.reason == "publish_blocked"


def test_a_knowledge_source_that_is_not_scanned_blocks_publishing(world):
    draft = create_draft(world, cfg=config(
        knowledge_document_ids=[str(world.document_id)],
        steps=[{"kind": "knowledge", "query": "pricing", "top_k": 3}, {"kind": "approval", "reason": "Check."}],
    ))
    with SessionLocal() as db:
        db.execute(update(Document).where(Document.id == world.document_id).values(scan_status="not_scanned"))
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            publish(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
    assert any("knowledge source" in problem for problem in refused.value.problems)
    with SessionLocal() as db:
        db.execute(update(Document).where(Document.id == world.document_id).values(scan_status="clean"))
        db.commit()


def test_rollback_points_at_an_earlier_version_without_copying_or_editing_it(world):
    draft = create_draft(world)
    first = publish_version(world, draft["id"])
    with TestingSessionLocal() as db:
        update_draft(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"],
                     configuration=config(purpose="Second purpose."))
        db.commit()
    second = publish_version(world, draft["id"])
    assert second.version_number == 2
    with SessionLocal() as db:
        rollback(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"], version_number=1)
        db.commit()
    assert agent_row(draft["id"]).current_version_id == first.id
    with SessionLocal() as db:
        versions = list_versions(db, organization_id=world.org.id, agent_id=draft["id"])
        assert [v.version_number for v in versions] == [2, 1]
        assert versions[0].configuration["purpose"] == "Second purpose."


def test_rolling_back_to_the_current_or_an_unknown_version_is_refused(world):
    draft = create_draft(world)
    publish_version(world, draft["id"])
    with SessionLocal() as db:
        with pytest.raises(AgentError):
            rollback(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"], version_number=1)
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            rollback(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"], version_number=9)
    assert refused.value.reason == "version_not_found"


# --- pause, resume and archive -----------------------------------------------------------------------------


def test_pause_and_resume_change_status_and_a_paused_agent_cannot_be_published(world):
    draft = create_draft(world)
    publish_version(world, draft["id"])
    with SessionLocal() as db:
        pause(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
        db.commit()
    assert agent_row(draft["id"]).status == "paused"
    with SessionLocal() as db:
        with pytest.raises(AgentError):
            publish(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
    with SessionLocal() as db:
        resume(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
        db.commit()
    assert agent_row(draft["id"]).status == "published"


def test_resume_revalidates_and_refuses_when_the_ai_capability_is_off(world):
    draft = create_draft(world)
    publish_version(world, draft["id"])
    with SessionLocal() as db:
        pause(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
        set_capability_enabled(db, organization_id=world.org.id, actor_user_id=world.owner.id,
                               capability_key="ai.agents", is_enabled=False)
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            resume(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
    assert refused.value.reason == "publish_blocked"
    assert agent_row(draft["id"]).status == "paused"


def test_archive_is_terminal_and_blocks_further_changes(world):
    draft = create_draft(world)
    publish_version(world, draft["id"])
    with SessionLocal() as db:
        archive(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(AgentError) as refused:
            update_draft(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"], name="again")
    assert refused.value.reason == "invalid_agent_state"


# --- preview ---------------------------------------------------------------------------------------------------


def test_preview_describes_the_plan_and_calls_no_tool_or_model(world, monkeypatch):
    calls = []
    monkeypatch.setattr(tool_service, "invoke_tool", lambda *a, **k: calls.append(1))
    draft = create_draft(world)
    with SessionLocal() as db:
        result = preview(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=draft["id"])
        db.commit()
    assert result["side_effects"] is False
    assert result["publishable"] is True
    assert [item["kind"] for item in result["plan"]] == ["tool", "model"]
    assert calls == []


def test_a_tool_the_publisher_cannot_use_makes_the_draft_unpublishable(world):
    member = create_user_in(world.org, permissions=("agents.read", "contacts.read"))
    draft = create_draft(world, cfg=config(
        tools=["leads.get"],
        steps=[{"kind": "tool", "tool": "leads.get", "arguments": {"lead_id": "$input.contact"}},
               {"kind": "approval", "reason": "Check the lead."}],
    ))
    with SessionLocal() as db:
        result = preview(db, organization_id=world.org.id, actor_id=member.id, agent_id=draft["id"])
        db.commit()
    assert result["publishable"] is False
    assert any("leads.get" in problem for problem in result["problems"])
