
"""Endpoint tests for billing webhook verification and ingestion."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.billing_webhooks import router
from app.billing.providers.fake import FakeBillingProvider
from app.billing.providers.registry import BillingProviderRegistry
from app.db.session import get_db_session


SECRET = b"fake-webhook-secret"


def signed_payload(event: dict) -> tuple[bytes, str]:
    body = json.dumps(event, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(
        SECRET, body, hashlib.sha256
    ).hexdigest()
    return body, signature


def create_app(monkeypatch, *, register_provider=True):
    app = FastAPI()
    app.include_router(router)

    registry = BillingProviderRegistry()
    if register_provider:
        registry.register("fake", FakeBillingProvider)
    app.state.billing_provider_registry = registry

    def override_db():
        yield SimpleNamespace(
            commit=lambda: None,
            rollback=lambda: None,
        )

    app.dependency_overrides[get_db_session] = override_db

    calls = []

    def fake_ingest(db, verified):
        calls.append(verified)
        return SimpleNamespace(
            event=SimpleNamespace(
                id=uuid4(),
                status="RECEIVED",
            ),
            created=len(calls) == 1,
        )

    monkeypatch.setattr(
        "app.api.billing_webhooks.ingest_verified_webhook",
        fake_ingest,
    )
    return app, calls


def test_valid_webhook_is_accepted(monkeypatch):
    app, calls = create_app(monkeypatch)
    body, signature = signed_payload(
        {"id": "evt-1", "type": "invoice.paid"}
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Provider-Signature": signature},
        )

    assert response.status_code == 202
    assert response.json()["received"] is True
    assert response.json()["duplicate"] is False
    assert len(calls) == 1


def test_invalid_signature_is_rejected(monkeypatch):
    app, calls = create_app(monkeypatch)
    body, _ = signed_payload(
        {"id": "evt-2", "type": "invoice.paid"}
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Provider-Signature": "sha256=invalid"},
        )

    assert response.status_code == 400
    assert calls == []


def test_missing_signature_is_rejected(monkeypatch):
    app, calls = create_app(monkeypatch)
    body, _ = signed_payload(
        {"id": "evt-3", "type": "invoice.paid"}
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/billing/webhooks/fake",
            content=body,
        )

    assert response.status_code == 400
    assert calls == []


def test_unregistered_provider_returns_service_unavailable(monkeypatch):
    app, calls = create_app(monkeypatch, register_provider=False)
    body, signature = signed_payload(
        {"id": "evt-4", "type": "invoice.paid"}
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Provider-Signature": signature},
        )

    assert response.status_code == 503
    assert calls == []


def test_duplicate_delivery_returns_ok(monkeypatch):
    app, calls = create_app(monkeypatch)
    body, signature = signed_payload(
        {"id": "evt-5", "type": "invoice.paid"}
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Provider-Signature": signature},
        )
        second = client.post(
            "/api/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Provider-Signature": signature},
        )

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert len(calls) == 2
