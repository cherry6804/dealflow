"""The read-only SIBVO access endpoint only reflects SIBVO's snapshot."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.user import User
from app.errors import register_error_handlers

SNAPSHOT = {
    "subscription_status": "trialing",
    "plan_version_id": str(uuid.uuid4()),
    "product_role": "owner",
    "entitlements": [
        {
            "feature_key": "workflow_automation",
            "enabled": True,
            "limit_value": None,
            "limit_unit": None,
        }
    ],
}


def client_for(context: CurrentUserContext) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    return TestClient(app)


def make_user() -> User:
    return User(id=uuid.uuid4(), email="agent@example.com", display_name="Agent")


def test_sso_session_returns_sibvo_snapshot() -> None:
    client = client_for(
        CurrentUserContext(user=make_user(), sibvo_attested=True, sibvo_access=SNAPSHOT)
    )

    response = client.get("/api/v1/auth/sibvo-access")

    assert response.status_code == 200
    assert response.json() == SNAPSHOT


def test_unattested_or_unchecked_session_has_no_snapshot() -> None:
    legacy = client_for(CurrentUserContext(user=make_user()))
    unchecked = client_for(
        CurrentUserContext(user=make_user(), sibvo_attested=True, sibvo_access=None)
    )

    assert legacy.get("/api/v1/auth/sibvo-access").status_code == 404
    assert unchecked.get("/api/v1/auth/sibvo-access").status_code == 404
