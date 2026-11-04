"""Agent HTTP routes: permissions, tenant scope, error reasons and the execution lifecycle over HTTP (DFR1-019)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import runtime
from app.api.agents import router as agents_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.session import get_db_session
from tests.agents_support import config, create_user_in, model_reply, use_provider
from tests.test_team_api import TestingSessionLocal


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(agents_router)

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


def test_the_tool_catalogue_lists_only_the_approved_registry_tools(world):
    client = _client(world.owner, world.org)
    body = client.get("/api/v1/agents/tools").json()
    keys = [item["key"] for item in body["items"]]
    assert keys == sorted(keys) and "contacts.get" in keys
    assert all(item["required_permission"].endswith(".read") for item in body["items"])


def test_create_publish_and_run_over_http_returns_the_stored_execution_on_repeat(world, monkeypatch):
    use_provider(monkeypatch, model_reply("Over HTTP."))
    client = _client(world.owner, world.org)
    created = client.post("/api/v1/agents", json={"name": "http-agent", "configuration": config()})
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    published = client.post(f"/api/v1/agents/{agent_id}/publish")
    assert published.status_code == 201, published.text
    assert published.json()["version_number"] == 1

    runner = _client(world.member, world.org)
    key = f"http-{uuid.uuid4().hex}"
    body = {"input": {"contact": str(world.contact_id)}, "idempotency_key": key}
    first = runner.post(f"/api/v1/agents/{agent_id}/executions", json=body)
    assert first.status_code == 202, first.text
    assert first.json()["created"] is True
    second = runner.post(f"/api/v1/agents/{agent_id}/executions", json=body)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["created"] is False

    detail = runner.get(f"/api/v1/agents/executions/{first.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "queued"
    assert detail.json()["steps"] == []


def test_a_member_without_the_run_permission_is_refused_with_a_reason(world):
    reader = create_user_in(world.org, permissions=("agents.read",))
    client = _client(reader, world.org)
    response = client.post(f"/api/v1/agents/{uuid.uuid4()}/executions",
                           json={"input": {}, "idempotency_key": "x"})
    assert response.status_code == 403


def test_another_organization_gets_not_found_for_an_agent_and_its_executions(world):
    created = _client(world.owner, world.org).post("/api/v1/agents", json={"name": "private-agent", "configuration": config()})
    agent_id = created.json()["id"]
    other = _client(world.other, world.other_org)
    assert other.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert other.get(f"/api/v1/agents/{agent_id}/executions").status_code == 404
    assert other.get(f"/api/v1/agents/executions/{uuid.uuid4()}").status_code == 404


def test_an_invalid_configuration_is_refused_with_its_problems(world):
    response = _client(world.owner, world.org).post(
        "/api/v1/agents", json={"name": "bad", "configuration": config(tools=["deals.delete"])})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "invalid_configuration"
    assert any("approved registry" in problem for problem in detail["problems"])


def test_a_cancel_over_http_stops_a_queued_execution(world, monkeypatch):
    use_provider(monkeypatch, model_reply())
    client = _client(world.owner, world.org)
    agent_id = client.post("/api/v1/agents", json={"name": "cancel-agent", "configuration": config()}).json()["id"]
    client.post(f"/api/v1/agents/{agent_id}/publish")
    runner = _client(world.member, world.org)
    execution = runner.post(f"/api/v1/agents/{agent_id}/executions", json={
        "input": {"contact": str(world.contact_id)}, "idempotency_key": f"c-{uuid.uuid4().hex}"}).json()
    cancelled = runner.post(f"/api/v1/agents/executions/{execution['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert runtime.EXECUTION_REQUESTED_EVENT
