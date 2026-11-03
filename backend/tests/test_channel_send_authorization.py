"""Channel sending is authorized by an explicit permission, and nothing grants it by default.

Decision (see docs/architecture/e13-completion-evidence.md, section 6): ADR-0029 gate 5 requires that the initiating
user holds permission on the target. ADR-0028 (channels) is still Proposed and names no send permission. So the gate
keeps the default key (``ai.execute``), which is not in the permission catalogue. No role can hold it, and the actor
gate refuses every channel send until a send permission is approved and catalogued.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import delete

from app.authz.permissions import PERMISSION_DESCRIPTIONS
from app.db.models.audit_event import AuditEvent
from app.db.session import SessionLocal
from app.governance import execution_gate
from app.governance.execution_gate import ExecutionRequest, actor_permission_granted
from tests.governance_helpers import attested_user_context
from tests.test_team_api import create_manager, create_owner_manager

CHANNEL_CAPABILITY = "channels.email"


@pytest.fixture
def cleanup() -> Iterator[list[uuid.UUID]]:
    created: list[uuid.UUID] = []
    yield created
    with SessionLocal() as db:
        for organization_id in created:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


def _request(user, organization_id: uuid.UUID) -> ExecutionRequest:
    return ExecutionRequest(
        organization_id=organization_id,
        capability_key=CHANNEL_CAPABILITY,
        user_context=attested_user_context(user, organization_id=organization_id),
        resource_id=str(uuid.uuid4()),
    )


def test_the_default_send_permission_is_not_in_the_catalogue() -> None:
    assert execution_gate.DEFAULT_AI_PERMISSION not in PERMISSION_DESCRIPTIONS


def test_an_owner_is_refused_because_no_role_can_hold_the_default_permission(cleanup) -> None:
    user, organization = create_owner_manager(permissions=("governance.consent.read",))
    cleanup.append(organization.id)
    with SessionLocal() as db:
        assert actor_permission_granted(
            db,
            organization_id=organization.id,
            user_id=user.id,
            permission_key=execution_gate.DEFAULT_AI_PERMISSION,
        ) is False
        outcomes: list = []
        denial = execution_gate._gate_actor(db, _request(user, organization.id), outcomes)
        assert denial is not None and denial.allowed is False
        assert denial.reason_code == "permission_denied"


def test_a_member_without_a_send_permission_is_refused(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.consent.read",))
    cleanup.append(organization.id)
    with SessionLocal() as db:
        outcomes: list = []
        denial = execution_gate._gate_actor(db, _request(user, organization.id), outcomes)
        assert denial is not None and denial.reason_code == "permission_denied"


def test_an_actor_holding_the_permission_passes_the_actor_gate(cleanup, monkeypatch) -> None:
    """The mechanism works when a send permission is granted. The key is a test-only grant, not a product key."""
    user, organization = create_manager(permissions=("governance.consent.read",))
    cleanup.append(organization.id)
    monkeypatch.setattr(execution_gate, "DEFAULT_AI_PERMISSION", "governance.consent.read")
    with SessionLocal() as db:
        assert actor_permission_granted(
            db,
            organization_id=organization.id,
            user_id=user.id,
            permission_key="governance.consent.read",
        ) is True
        outcomes: list = []
        assert execution_gate._gate_actor(db, _request(user, organization.id), outcomes) is None
        assert outcomes[-1].allowed is True
