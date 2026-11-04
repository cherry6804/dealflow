"""Shared fixtures and helpers for the agent tests (DFR1-019).

The tests use the real database, the real permission and membership checks, the real execution gate, the real outbox and the real
audit tables. Only the provider boundary is scripted, and the approval-pending seams are the same as in the AI gateway tests.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.ai_gateway.tasks import TaskType
from app.config import get_settings
from app.db.models.agent import Agent, AgentExecution, AgentExecutionStep, AgentVersion
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.document import Document
from app.db.models.organization import Organization
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal
from app.governance import execution_gate
from app.governance.capabilities import AI_MASTER
from app.governance.service import set_capability_enabled
from tests.governance_helpers import (
    allow_actor_execution_permission,
    allow_organization_entitlements,
    allow_provider_readiness,
)
from tests.test_ai_gateway import (
    SECRET_PREFIX,
    _configure_budgets,
    _ok_text,
    _Provider,
    _set_route,
    _store_credential,
    _use_provider,
)
from tests.test_deals_api import create_membership, create_user, grant_permission
from tests.test_team_api import create_owner_manager

AGENT_CAPABILITY = "ai.agents"
ASSISTANT_CAPABILITY = "ai.assistant"
TEXT_ROUTE_MODEL = "agent-test-model"


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


@pytest.fixture
def keyring(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "test-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"test-v1": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def config(**overrides) -> dict:
    """A valid draft with one tool step, one model step and a before-result approval policy."""
    base = {
        "category": "sales",
        "purpose": "Summarise a contact for a salesperson.",
        "instructions": "Be concise and factual.",
        "language": "en",
        "autonomy_level": "suggest",
        "approval_policy": "before_result",
        "tools": ["contacts.get"],
        "inputs": [{"name": "contact", "type": "uuid", "required": True}],
        "steps": [
            {"kind": "tool", "tool": "contacts.get", "arguments": {"contact_id": "$input.contact"}},
            {"kind": "model", "prompt": "Summarise the contact in one line.", "output_schema": {"summary": "string"}},
        ],
        "limits": {
            "max_duration_seconds": 60,
            "max_steps": 5,
            "max_tool_calls": 2,
            "max_retries": 1,
            "max_output_characters": 4000,
            "max_concurrent_executions": 2,
            "max_executions_per_hour": 50,
        },
    }
    base.update(overrides)
    return base


def enable_ai(monkeypatch, organization, actor) -> None:
    """Switch on the organization's AI, the agent capability and the tool capability, and allow the approval-pending seams."""
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    allow_actor_execution_permission(monkeypatch, "governance.consent.read")
    for capability in (AGENT_CAPABILITY, ASSISTANT_CAPABILITY):
        monkeypatch.setitem(execution_gate.RATE_EXECUTION_TYPE, capability, f"agents_test_{capability}")
    monkeypatch.setattr(execution_gate, "consume_or_deny",
                        lambda db, **kwargs: SimpleNamespace(allowed=True, reason_code="allowed"))

    def passed(db, request, outcomes):
        from app.governance.execution_gate import GateOutcome
        outcomes.append(GateOutcome(gate="resource", allowed=True, reason_code="allowed_all"))

    monkeypatch.setattr(execution_gate, "_gate_resource", passed)
    with SessionLocal() as db:
        for key in (AI_MASTER, AGENT_CAPABILITY, ASSISTANT_CAPABILITY):
            set_capability_enabled(db, organization_id=organization.id, actor_user_id=actor.id,
                                   capability_key=key, is_enabled=True)
        db.commit()
    _configure_budgets(organization.id, output=10_000, inputs=10_000)
    _store_credential(organization.id, actor.id, f"{SECRET_PREFIX}agents")
    _set_route(organization.id, actor.id, TaskType.TEXT, model=TEXT_ROUTE_MODEL)


def model_reply(summary: str = "A useful summary.") -> object:
    return _ok_text(json.dumps({"summary": summary}))


def use_provider(monkeypatch, *responses) -> _Provider:
    provider = _Provider(*responses)
    _use_provider(monkeypatch, provider)
    return provider


@pytest.fixture
def world(monkeypatch, keyring) -> Iterator[SimpleNamespace]:
    """Organization A: an owner who holds every permission, a member who can run agents, a contact and an eligible document.
    Organization B: an unrelated owner. Every test starts from this state and the fixture removes what it created."""
    owner, org = create_owner_manager(permissions=("agents.read",))
    member_user = create_user_in(org, permissions=("agents.read", "agents.run", "contacts.read", "documents.read",
                                                  "governance.consent.read"))
    other, other_org = create_owner_manager(permissions=("agents.read",))
    with SessionLocal() as db:
        contact = Contact(organization_id=org.id, first_name="Ada", last_name="Lovelace", is_active=True,
                          email="ada@example.test")
        db.add(contact)
        db.flush()
        document = Document(
            organization_id=org.id, original_filename="guide.txt", display_name="guide", category=Document.CATEGORY_AGREEMENT,
            document_type="Guide", content_type="text/plain", file_extension=".txt", file_size_bytes=10,
            checksum_sha256="0" * 64, storage_backend="local", storage_key=f"{org.id}/{uuid.uuid4().hex}.txt",
            access_classification=Document.CLASSIFICATION_INTERNAL, status=Document.STATUS_AVAILABLE,
            scan_status=Document.SCAN_CLEAN, uploaded_by_user_id=owner.id, created_by_user_id=owner.id,
        )
        db.add(document)
        db.commit()
        contact_id, document_id = contact.id, document.id
    monkeypatch.setenv("PROVIDER_LIVE_ADAPTERS_ENABLED", "true")
    get_settings.cache_clear()
    enable_ai(monkeypatch, org, owner)
    yield SimpleNamespace(owner=owner, org=org, member=member_user, other=other, other_org=other_org,
                          contact_id=contact_id, document_id=document_id)
    cleanup(org.id, other_org.id)


def create_user_in(organization, *, permissions: tuple[str, ...]):
    with SessionLocal() as db:
        user = create_user(db)
        membership = create_membership(db, user=user, organization=db.get(Organization, organization.id))
        for key in permissions:
            grant_permission(db, membership=membership, permission_key=key)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def cleanup(*organization_ids) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            db.execute(delete(AgentExecutionStep).where(AgentExecutionStep.organization_id == organization_id))
            db.execute(delete(AgentExecution).where(AgentExecution.organization_id == organization_id))
            db.execute(delete(AgentVersion).where(AgentVersion.organization_id == organization_id))
            db.execute(delete(Agent).where(Agent.organization_id == organization_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
            db.execute(delete(Document).where(Document.organization_id == organization_id))
            db.execute(delete(Contact).where(Contact.organization_id == organization_id))
        db.commit()


def create_draft(world, *, cfg: dict | None = None, name: str | None = None) -> dict:
    from app.agents.service import create_agent
    with SessionLocal() as db:
        agent = create_agent(db, organization_id=world.org.id, actor_id=world.owner.id,
                             name=name or f"agent-{uuid.uuid4().hex[:8]}", description="test",
                             configuration=cfg or config())
        db.commit()
        return {"id": agent.id}


def publish(world, agent_id) -> AgentVersion:
    from app.agents.service import publish as do_publish
    with SessionLocal() as db:
        version = do_publish(db, organization_id=world.org.id, actor_id=world.owner.id, agent_id=agent_id)
        db.commit()
        db.refresh(version)
        db.expunge(version)
        return version


def agent_row(agent_id) -> Agent:
    with SessionLocal() as db:
        row = db.get(Agent, agent_id)
        db.expunge(row)
        return row


def execution_row(execution_id) -> AgentExecution:
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        db.expunge(row)
        return row


def steps_of(execution_id) -> list[AgentExecutionStep]:
    with SessionLocal() as db:
        rows = db.scalars(select(AgentExecutionStep).where(AgentExecutionStep.execution_id == execution_id)
                          .order_by(AgentExecutionStep.step_index)).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def audit_for(organization_id, action: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id,
                                                   AuditEvent.action == action)).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def now_utc() -> datetime:
    return datetime.now(UTC)
