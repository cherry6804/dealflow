"""The seat capacity endpoint shows SIBVO's seat figures to product owners only."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.user import User
from app.errors import register_error_handlers
from app.integrations import sibvo_client
from app.integrations.sibvo_client import SibvoSeatUsage, SibvoUnavailable


def owner_context(**overrides) -> CurrentUserContext:
    values = {
        "user": User(id=uuid.uuid4(), email="owner@example.com", display_name="Owner"),
        "sibvo_attested": True,
        "sibvo_access": {"product_role": "owner", "entitlements": []},
        "sibvo_subject": uuid.uuid4(),
        "sibvo_session_id": uuid.uuid4(),
        "sibvo_organization_id": uuid.uuid4(),
    }
    values.update(overrides)
    return CurrentUserContext(**values)


def client_for(context: CurrentUserContext) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[get_current_user_context] = lambda: context
    return TestClient(app)


def test_owner_sees_seat_capacity_from_sibvo(monkeypatch: pytest.MonkeyPatch) -> None:
    context = owner_context()
    seen: dict = {}

    def fake(settings, *, subject, session_id, organization_id):
        seen.update(subject=subject, session_id=session_id, organization_id=organization_id)
        return SibvoSeatUsage(
            organization_id=organization_id,
            product_key="dealsflo",
            seat_limit=5,
            allocated=3,
            reserved=1,
            available=1,
        )

    monkeypatch.setattr(sibvo_client, "fetch_seat_usage", fake)

    response = client_for(context).get("/api/v1/auth/sibvo-seats")

    assert response.status_code == 200
    assert response.json() == {
        "seat_limit": 5,
        "allocated": 3,
        "reserved": 1,
        "available": 1,
        "unlimited": False,
    }
    # The call uses the identifiers bound to this session, never client input.
    assert seen == {
        "subject": context.sibvo_subject,
        "session_id": context.sibvo_session_id,
        "organization_id": context.sibvo_organization_id,
    }


def test_unlimited_plan_reports_no_seat_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    context = owner_context()
    monkeypatch.setattr(
        sibvo_client,
        "fetch_seat_usage",
        lambda settings, **kwargs: SibvoSeatUsage(
            organization_id=kwargs["organization_id"],
            product_key="dealsflo",
            seat_limit=None,
            allocated=7,
            reserved=0,
            available=None,
        ),
    )

    body = client_for(context).get("/api/v1/auth/sibvo-seats").json()

    assert body == {
        "seat_limit": None,
        "allocated": 7,
        "reserved": 0,
        "available": None,
        "unlimited": True,
    }


def test_member_cannot_see_seat_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(sibvo_client, "fetch_seat_usage", lambda *a, **k: called.append(1))
    context = owner_context(sibvo_access={"product_role": "member", "entitlements": []})

    response = client_for(context).get("/api/v1/auth/sibvo-seats")

    assert response.status_code == 403
    assert called == []


def test_unattested_session_has_no_seat_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sibvo_client, "fetch_seat_usage", lambda *a, **k: None)
    context = owner_context(sibvo_attested=False, sibvo_access=None)

    response = client_for(context).get("/api/v1/auth/sibvo-seats")

    assert response.status_code == 404


def test_sibvo_denial_is_reported_without_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sibvo_client, "fetch_seat_usage", lambda *a, **k: None)

    response = client_for(owner_context()).get("/api/v1/auth/sibvo-seats")

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Seat capacity is not available for this session."


def test_sibvo_outage_reports_seat_information_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*args, **kwargs):
        raise SibvoUnavailable("SIBVO could not be reached.")

    monkeypatch.setattr(sibvo_client, "fetch_seat_usage", down)

    response = client_for(owner_context()).get("/api/v1/auth/sibvo-seats")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "SIBVO seat information is unavailable."
