"""Governance capability API: permissions, confirmation, audit and tenant scoping."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.governance import router as governance_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.session import SessionLocal, get_db_session
from app.governance.capabilities import AUTOMATION_MASTER
from tests.test_team_api import TestingSessionLocal, create_manager

BASE = "/api/v1/governance/capabilities"


def _app_for(user) -> FastAPI:
    app = FastAPI()
    app.include_router(governance_router)

    def override_get_db_session() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    return app


@pytest.fixture
def cleanup():
    created: list = []
    yield created
    with SessionLocal() as db:
        for organization_id in created:
            db.execute(
                delete(OrganizationCapabilitySetting).where(
                    OrganizationCapabilitySetting.organization_id == organization_id
                )
            )
            db.execute(
                delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
            )
        db.commit()


def test_listing_requires_the_read_permission(cleanup) -> None:
    user, organization = create_manager(permissions=("deals.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(BASE)

    assert response.status_code == 403


def test_listing_shows_every_capability_disabled_by_default(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(BASE)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "catalogue must not be empty"
    assert all(item["is_enabled"] is False for item in items)
    assert all(item["effective"]["allowed"] is False for item in items)
    assert all(item["effective"]["reason_code"] for item in items)


def test_changing_a_capability_requires_the_manage_permission(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.patch(
            f"{BASE}/{AUTOMATION_MASTER}", json={"is_enabled": True, "confirm": True}
        )

    assert response.status_code == 403


def test_change_requires_explicit_confirmation(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.manage",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        missing = client.patch(f"{BASE}/{AUTOMATION_MASTER}", json={"is_enabled": True})
        refused = client.patch(
            f"{BASE}/{AUTOMATION_MASTER}", json={"is_enabled": True, "confirm": False}
        )

    assert missing.status_code == 422
    assert refused.status_code == 422


def test_unknown_capability_returns_not_found(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.manage",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.patch(
            f"{BASE}/ai.not_real", json={"is_enabled": True, "confirm": True}
        )

    assert response.status_code == 404


def test_change_is_persisted_versioned_and_audited(cleanup) -> None:
    user, organization = create_manager(
        permissions=("governance.capabilities.manage", "governance.capabilities.read")
    )
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.patch(
            f"{BASE}/{AUTOMATION_MASTER}", json={"is_enabled": True, "confirm": True}
        )
        listing = client.get(BASE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_enabled"] is True
    assert body["policy_version"] == 1

    master = next(item for item in listing.json()["items"] if item["capability_key"] == AUTOMATION_MASTER)
    assert master["is_enabled"] is True

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization.id,
                AuditEvent.event_type == "governance",
            )
        ).all()
    assert len(events) == 1
    assert events[0].resource_id == AUTOMATION_MASTER
    assert events[0].user_id == user.id
    assert json.loads(events[0].event_metadata) == {
        "after": True,
        "before": False,
        "policy_version": 1,
    }


def test_settings_of_one_organization_cannot_be_changed_with_another_tenant(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.manage",))
    cleanup.append(organization.id)
    _, other_organization = create_manager(permissions=())
    cleanup.append(other_organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(other_organization.id)})
        response = client.patch(
            f"{BASE}/{AUTOMATION_MASTER}", json={"is_enabled": True, "confirm": True}
        )

    assert response.status_code == 403

    with SessionLocal() as db:
        rows = db.scalars(
            select(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == other_organization.id
            )
        ).all()
    assert rows == []


def test_access_endpoint_reports_the_callers_governance_permissions(cleanup) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get("/api/v1/governance/access")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "capabilities_read": True,
        "capabilities_manage": False,
        "usage_read": False,
        "budgets_manage": False,
        "privacy_read": False,
        "privacy_manage": False,
    }
