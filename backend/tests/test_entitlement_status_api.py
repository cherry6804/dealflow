"""WS6 WP7: the entitlement status contract for the governance settings page.

The endpoint reports the operational state of SIBVO's snapshot. It must never expose the snapshot body,
a signature, or the signing key, and it is gated by the same permission as the capability list.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete

from app.api.governance import router as governance_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.organization_entitlement_snapshot import (
    OrganizationEntitlementSnapshot,
)
from app.db.session import SessionLocal, get_db_session
from app.governance import org_entitlement
from tests.test_team_api import TestingSessionLocal, create_manager

BASE = "/api/v1/governance/entitlement-status"
SIGNING_KEY = "s" * 40


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
def signing_key(monkeypatch):
    settings = get_settings().model_copy(update={"sibvo_org_snapshot_signing_key": SecretStr(SIGNING_KEY)})
    monkeypatch.setattr(org_entitlement, "get_settings", lambda: settings)
    monkeypatch.setattr("app.api.governance.get_settings", lambda: settings)
    return settings


@pytest.fixture
def cleanup():
    created: list = []
    yield created
    with SessionLocal() as db:
        for organization_id in created:
            db.execute(delete(OrganizationEntitlementSnapshot).where(
                OrganizationEntitlementSnapshot.organization_id == organization_id))
        db.commit()


def test_status_requires_the_capability_read_permission(cleanup) -> None:
    user, organization = create_manager(permissions=("deals.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(BASE)

    assert response.status_code == 403


def test_status_reports_missing_and_never_leaks_secrets(cleanup, signing_key) -> None:
    user, organization = create_manager(permissions=("governance.capabilities.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(BASE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "missing"
    assert body["signing_key_configured"] is True
    assert body["revalidation_interval_seconds"] == 30
    text = response.text
    assert SIGNING_KEY not in text
    assert "snapshot_body" not in text
    assert "signature" not in text


def test_status_reports_no_signing_key_as_a_flag_only(cleanup, monkeypatch) -> None:
    unconfigured = get_settings().model_copy(update={"sibvo_org_snapshot_signing_key": None})
    monkeypatch.setattr("app.api.governance.get_settings", lambda: unconfigured)
    user, organization = create_manager(permissions=("governance.capabilities.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(BASE)

    assert response.status_code == 200
    assert response.json()["signing_key_configured"] is False
