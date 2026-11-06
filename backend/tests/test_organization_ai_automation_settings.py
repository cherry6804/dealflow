"""Agent activation controls for organization AI and automation settings (DFR1-036).

The capability switches, master and child controls, entitlement fail-closed behaviour, consent and budget gates, manual CRM
continuity, and workflow activation are covered by the existing suites (``test_capability_policy_gates.py``,
``test_governance_policy.py``, ``test_governance_entitlement.py``, ``test_governance_api.py``, ``test_workflow_runtime.py``,
``test_workflow_definitions.py``). This module adds the agent activation cases that those suites did not name: a paused agent
refuses new work, resuming creates no version or execution, a repeated request after resume returns the stored execution, and
the pause and resume routes enforce the publish permission and tenant scope.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.agents.runtime import create_execution
from app.agents.service import AgentError, pause, resume
from app.auth.dependencies import CurrentUserContext
from app.db.models.agent import Agent, AgentExecution, AgentVersion
from app.db.models.user import User
from app.db.session import SessionLocal
from tests.agents_support import config, create_draft, create_user_in, publish
from tests.test_agents_api import _client


def _user(user_id) -> User:
    with SessionLocal() as db:
        row = db.get(User, user_id)
        db.expunge(row)
        return row


def _counts(agent_id) -> tuple[int, int]:
    with SessionLocal() as db:
        versions = db.scalar(
            select(func.count())
            .select_from(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
        )
        executions = db.scalar(
            select(func.count())
            .select_from(AgentExecution)
            .where(AgentExecution.agent_id == agent_id)
        )
        return versions, executions


def _status(agent_id) -> str:
    with SessionLocal() as db:
        return db.get(Agent, agent_id).status


def _start(world, agent_id, key):
    with SessionLocal() as db:
        execution, created = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=agent_id,
            user_context=CurrentUserContext(user=_user(world.member.id)),
            input_values={"contact": str(world.contact_id)},
            idempotency_key=key,
        )
        db.commit()
        return execution.id, created


def _published_agent(world) -> str:
    draft = create_draft(world)
    publish(world, draft["id"])
    return draft["id"]


def test_a_paused_agent_refuses_new_work_with_a_stable_reason(world):
    agent_id = _published_agent(world)
    with SessionLocal() as db:
        pause(
            db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id
        )
        db.commit()
    try:
        _start(world, agent_id, key=f"paused-{uuid.uuid4().hex}")
    except AgentError as error:
        assert error.reason == "agent_not_active"
    else:
        raise AssertionError("a paused agent must not start a new execution")
    assert _counts(agent_id)[1] == 0


def test_resuming_creates_no_version_and_no_execution(world):
    agent_id = _published_agent(world)
    before = _counts(agent_id)
    with SessionLocal() as db:
        pause(
            db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id
        )
        db.commit()
    with SessionLocal() as db:
        resume(
            db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id
        )
        db.commit()
    assert _status(agent_id) == "published"
    assert _counts(agent_id) == before, (
        "re-enabling must not create a version or an execution"
    )


def test_a_repeated_request_after_resume_returns_the_stored_execution(world):
    agent_id = _published_agent(world)
    key = f"resume-{uuid.uuid4().hex}"
    first_id, created = _start(world, agent_id, key)
    assert created is True
    with SessionLocal() as db:
        pause(
            db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id
        )
        resume(
            db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id
        )
        db.commit()
    second_id, created_again = _start(world, agent_id, key)
    assert created_again is False
    assert second_id == first_id
    assert _counts(agent_id)[1] == 1


def test_pause_and_resume_over_http_need_the_publish_permission(world):
    agent_id = (
        _client(world.owner, world.org)
        .post(
            "/api/v1/agents",
            json={"name": "activation-agent", "configuration": config()},
        )
        .json()["id"]
    )
    assert (
        _client(world.owner, world.org)
        .post(f"/api/v1/agents/{agent_id}/publish")
        .status_code
        == 201
    )
    reader = create_user_in(world.org, permissions=("agents.read", "agents.run"))
    reader_client = _client(reader, world.org)
    assert reader_client.post(f"/api/v1/agents/{agent_id}/pause").status_code == 403
    assert _status(agent_id) == "published"

    owner_client = _client(world.owner, world.org)
    assert owner_client.post(f"/api/v1/agents/{agent_id}/pause").status_code == 200
    assert _status(agent_id) == "paused"
    assert reader_client.post(f"/api/v1/agents/{agent_id}/resume").status_code == 403
    assert _status(agent_id) == "paused"
    assert owner_client.post(f"/api/v1/agents/{agent_id}/resume").status_code == 200
    assert _status(agent_id) == "published"


def test_another_organization_cannot_pause_or_resume_an_agent(world):
    agent_id = _published_agent(world)
    other = _client(world.other, world.other_org)
    assert other.post(f"/api/v1/agents/{agent_id}/pause").status_code == 404
    assert _status(agent_id) == "published"
    with SessionLocal() as db:
        pause(
            db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id
        )
        db.commit()
    assert other.post(f"/api/v1/agents/{agent_id}/resume").status_code == 404
    assert _status(agent_id) == "paused"
