"""Trusted audit attribution (WS6 WP3 identity hardening).

Runs on PostgreSQL. The cases fall into four groups:

- inside a bound authenticated principal, attribution must match that principal exactly;
- outside a request, attribution is verified by active membership and labelled as such;
- system attribution requires the registered capability object, not a name;
- the authentication layer binds the principal for a real HTTP request, and the writer sees it.

Every refusal asserts that no audit row was written for the organization the caller claimed.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.api.governance import router as governance_router
from app.audit import independent as independent_module
from app.audit.attribution import (
    ATTRIBUTION_SOURCE_MEMBERSHIP,
    ATTRIBUTION_SOURCE_PRINCIPAL,
    ATTRIBUTION_SOURCE_SYSTEM,
    AuditAttribution,
    AuditAttributionError,
    SystemActorCapability,
    register_system_actor,
    system_attribution,
    user_attribution,
)
from app.audit.independent import OUTCOME_REQUESTED, persist_independent_audit_event
from app.audit.principal import TrustedPrincipal, bound_principal, issue_principal
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditEvent
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.session import SessionLocal, get_db_session
from app.governance.ai_execution import _AI_GATE_ACTOR
from app.governance.capabilities import AI_MASTER, AUTOMATION_MASTER
from app.governance.service import set_capability_enabled
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

EVENT_TYPE = "governance"
ACTION = "test.attribution"
BACKEND_APP = Path(__file__).resolve().parents[1] / "app"


def _cleanup(*organization_ids: UUID) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
            db.execute(delete(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization_id))
        db.commit()


@pytest.fixture
def tenants() -> Iterator[dict]:
    """Two organizations. Each has an owner and a second active member, and the members never cross."""
    owner_a, org_a = create_owner_manager(permissions=("governance.capabilities.manage",))
    member_a, _ = create_manager(permissions=())
    owner_b, org_b = create_owner_manager(permissions=("governance.capabilities.manage",))
    _link(member_a.id, org_a.id)
    yield {
        "org_a": org_a.id,
        "owner_a": owner_a.id,
        "member_a": member_a.id,
        "org_b": org_b.id,
        "owner_b": owner_b.id,
    }
    _cleanup(org_a.id, org_b.id)


def _link(user_id: UUID, organization_id: UUID) -> None:
    """Make ``user_id`` an active member of ``organization_id``, adding the membership if it is missing."""
    with SessionLocal() as db:
        existing = db.scalar(select(Membership.id).where(
            Membership.user_id == user_id, Membership.organization_id == organization_id))
        if existing is None:
            db.add(Membership(user_id=user_id, organization_id=organization_id, is_active=True))
            db.commit()
        else:
            db.execute(update(Membership).where(Membership.id == existing).values(is_active=True))
            db.commit()


def _rows(organization_id: UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id)).all())


def _write(attribution: AuditAttribution, *, idempotency_key: str | None = None) -> AuditEvent:
    return persist_independent_audit_event(
        SessionLocal(),
        attribution=attribution,
        event_type=EVENT_TYPE,
        action=ACTION,
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        idempotency_key=idempotency_key,
    )


def _principal(user_id: UUID, organization_id: UUID) -> TrustedPrincipal:
    return issue_principal(user_id=user_id, organization_id=organization_id)


# --- Inside an authenticated principal ------------------------------------------------------------


def test_the_bound_user_in_the_bound_organization_is_attributed(tenants) -> None:
    with bound_principal(_principal(tenants["owner_a"], tenants["org_a"])):
        attribution = user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["owner_a"])
        row = _write(attribution)

    assert attribution.source == ATTRIBUTION_SOURCE_PRINCIPAL
    assert row.user_id == tenants["owner_a"]
    assert row.organization_id == tenants["org_a"]


def test_a_caller_cannot_attribute_an_operation_to_another_active_user_of_the_same_organization(tenants) -> None:
    # member_a is an active member of organization A, but the authenticated principal is owner_a.
    with bound_principal(_principal(tenants["owner_a"], tenants["org_a"])), pytest.raises(AuditAttributionError):
        user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"])
    assert _rows(tenants["org_a"]) == []


def test_a_caller_cannot_attribute_an_operation_to_a_user_in_another_organization(tenants) -> None:
    # owner_b is a real user of organization B. The request is bound to organization A.
    with bound_principal(_principal(tenants["owner_a"], tenants["org_a"])):
        with pytest.raises(AuditAttributionError):
            user_attribution(organization_id=tenants["org_b"], actor_user_id=tenants["owner_b"])
        with pytest.raises(AuditAttributionError):
            user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["owner_b"])
    assert _rows(tenants["org_a"]) == []
    assert _rows(tenants["org_b"]) == []


def test_a_governed_change_cannot_be_attributed_to_another_member_of_the_same_organization(tenants) -> None:
    with bound_principal(_principal(tenants["owner_a"], tenants["org_a"])):
        with SessionLocal() as db, pytest.raises(AuditAttributionError):
            set_capability_enabled(db, organization_id=tenants["org_a"], actor_user_id=tenants["member_a"],
                                   capability_key=AUTOMATION_MASTER, is_enabled=True)
        db.rollback()
    with SessionLocal() as db:
        assert db.scalar(select(OrganizationCapabilitySetting.id).where(
            OrganizationCapabilitySetting.organization_id == tenants["org_a"])) is None
    assert _rows(tenants["org_a"]) == []


def test_a_principal_cannot_be_forged(tenants) -> None:
    with pytest.raises(TypeError):
        TrustedPrincipal(user_id=tenants["owner_a"], organization_id=tenants["org_a"], _issued=object())


def test_an_attribution_cannot_be_constructed_directly(tenants) -> None:
    with pytest.raises(TypeError):
        AuditAttribution(organization_id=tenants["org_a"], actor_user_id=tenants["owner_a"],
                         system_actor=None, source=ATTRIBUTION_SOURCE_PRINCIPAL, _issued=object())


# --- Outside a request: membership verification ---------------------------------------------------


def test_outside_a_request_an_active_member_is_attributed_and_labelled_as_membership(tenants) -> None:
    attribution = user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"])
    row = _write(attribution)
    assert attribution.source == ATTRIBUTION_SOURCE_MEMBERSHIP
    assert row.user_id == tenants["member_a"]


def test_outside_a_request_a_user_outside_the_organization_is_refused_by_the_writer(tenants) -> None:
    attribution = user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["owner_b"])
    with pytest.raises(AuditAttributionError):
        _write(attribution)
    assert _rows(tenants["org_a"]) == []


def test_an_inactive_membership_is_refused_outside_a_request(tenants) -> None:
    with SessionLocal() as db:
        db.execute(update(Membership).where(
            Membership.user_id == tenants["member_a"], Membership.organization_id == tenants["org_a"],
        ).values(is_active=False))
        db.commit()
    try:
        with pytest.raises(AuditAttributionError):
            _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"]))
        assert _rows(tenants["org_a"]) == []
    finally:
        _link(tenants["member_a"], tenants["org_a"])


def test_an_inactive_organization_is_refused_even_for_a_bound_principal(tenants) -> None:
    with SessionLocal() as db:
        db.execute(update(Organization).where(Organization.id == tenants["org_a"]).values(is_active=False))
        db.commit()
    try:
        with bound_principal(_principal(tenants["owner_a"], tenants["org_a"])), pytest.raises(AuditAttributionError):
            _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["owner_a"]))
        assert _rows(tenants["org_a"]) == []
    finally:
        with SessionLocal() as db:
            db.execute(update(Organization).where(Organization.id == tenants["org_a"]).values(is_active=True))
            db.commit()


# --- System attribution: capabilities, not names ---------------------------------------------------


def test_the_registered_gate_capability_writes_a_system_record(tenants) -> None:
    attribution = system_attribution(organization_id=tenants["org_a"], capability=_AI_GATE_ACTOR)
    row = _write(attribution)
    assert attribution.source == ATTRIBUTION_SOURCE_SYSTEM
    assert row.user_id is None
    assert row.organization_id == tenants["org_a"]


def test_a_system_name_is_not_a_capability(tenants) -> None:
    with pytest.raises(AuditAttributionError):
        system_attribution(organization_id=tenants["org_a"], capability="ai_execution_gate")  # type: ignore[arg-type]
    assert _rows(tenants["org_a"]) == []


def test_a_capability_cannot_be_constructed_directly(tenants) -> None:
    with pytest.raises(TypeError):
        SystemActorCapability("ai_execution_gate", object())


def test_a_look_alike_capability_is_refused(tenants) -> None:
    look_alike = SystemActorCapability.__new__(SystemActorCapability)
    look_alike.name = "ai_execution_gate"
    with pytest.raises(AuditAttributionError):
        system_attribution(organization_id=tenants["org_a"], capability=look_alike)
    assert _rows(tenants["org_a"]) == []


def test_a_system_actor_cannot_be_registered_twice(tenants) -> None:
    with pytest.raises(ValueError):
        register_system_actor("ai_execution_gate")


def test_a_system_record_inside_a_request_must_name_the_bound_organization(tenants) -> None:
    with bound_principal(_principal(tenants["owner_a"], tenants["org_a"])), pytest.raises(AuditAttributionError):
        system_attribution(organization_id=tenants["org_b"], capability=_AI_GATE_ACTOR)
    assert _rows(tenants["org_b"]) == []


# --- Only the authentication layer issues principals -----------------------------------------------


def test_only_the_authentication_layer_issues_principals() -> None:
    """Scan the application source: ``issue_principal`` may be called only by the tenant dependency."""
    allowed = {"app/audit/principal.py", "app/tenant/dependencies.py"}
    offenders = []
    for path in BACKEND_APP.rglob("*.py"):
        relative = path.relative_to(BACKEND_APP.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            is_issue_call = isinstance(node, ast.Call) and getattr(node.func, "id", None) == "issue_principal"
            if is_issue_call and relative not in allowed:
                offenders.append(relative)
    assert offenders == []


# --- End to end: the authentication layer binds the principal for a real request ------------------


def test_a_governed_request_is_attributed_to_the_authenticated_principal(tenants, monkeypatch) -> None:
    seen: list[tuple[UUID, UUID] | None] = []
    original = independent_module.persist_independent_audit_event

    def recording(source, *, attribution, **kwargs):
        from app.audit.principal import current_principal

        principal = current_principal()
        seen.append((principal.user_id, principal.organization_id) if principal else None)
        return original(source, attribution=attribution, **kwargs)

    monkeypatch.setattr("app.governance.service.persist_independent_audit_event", recording)

    user, organization = create_owner_manager(permissions=("governance.capabilities.manage",))
    app = FastAPI()
    app.include_router(governance_router)

    def db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.patch(
                f"/api/v1/governance/capabilities/{AI_MASTER}",
                json={"is_enabled": True, "confirm": True},
            )
    finally:
        _cleanup(organization.id)

    assert response.status_code == 200, response.text
    assert seen == [(user.id, organization.id)]
