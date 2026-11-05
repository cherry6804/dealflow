"""Verified inbound webhook ingress (DFR1-012).

These are mocked-boundary tests. The signature format under test is Dealsflo's synthetic ``hmac_sha256_v1`` format, and the provider
key ``acme_crm`` is a placeholder. A passing test shows that the verifier and the ingress behave as documented. It does not show that
any provider signs or sends webhooks this way, and it is not sandbox verification of any provider.

The tests use the real database, the real provider-secrets cipher with a test keyring, the real outbox table and the real audit table.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.webhook_ingress import admin_router, receiver_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.inbound_webhook import InboundWebhookDelivery, InboundWebhookEndpoint
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal, get_db_session
from app.outbox.service import PermanentHandlerError
from app.provider_secrets.redaction import ProviderSecret
from app.webhooks import service
from app.webhooks.envelope import MAX_BODY_BYTES, MalformedWebhook, normalize
from app.webhooks.handlers import register_webhook_handlers
from app.webhooks.redaction import redact_payload
from app.webhooks.verifier import HmacSha256Verifier
from tests.agents_support import create_user_in
from tests.test_team_api import TestingSessionLocal, create_owner_manager

PROVIDER = "acme_crm"
VERIFIER = "hmac_sha256_v1"
OWNER_PERMISSIONS = ("webhook_endpoints.manage",)
READER_PERMISSIONS = ("leads.read",)


def _key() -> str:
    import base64
    import os

    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


@pytest.fixture
def keyring(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "test-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"test-v1": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _cleanup(organization_ids) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            db.execute(
                delete(InboundWebhookDelivery).where(
                    InboundWebhookDelivery.organization_id == organization_id
                )
            )
            db.execute(
                delete(InboundWebhookEndpoint).where(
                    InboundWebhookEndpoint.organization_id == organization_id
                )
            )
            db.execute(
                delete(OutboxEvent).where(
                    OutboxEvent.organization_id == organization_id
                )
            )
            db.execute(
                delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
            )
        db.commit()


@pytest.fixture
def orgs(keyring) -> Iterator[SimpleNamespace]:
    owner, org = create_owner_manager(permissions=OWNER_PERMISSIONS)
    other, other_org = create_owner_manager(permissions=OWNER_PERMISSIONS)
    reader = create_user_in(org, permissions=READER_PERMISSIONS)
    yield SimpleNamespace(
        owner=owner, org=org, other=other, other_org=other_org, reader=reader
    )
    _cleanup((org.id, other_org.id))


def _endpoint(orgs, *, org=None, label: str = "Inbound CRM") -> tuple[uuid.UUID, str]:
    org = org or orgs.org
    with SessionLocal() as db:
        row, secret = service.create_endpoint(
            db,
            organization_id=org.id,
            actor_id=orgs.owner.id if org.id == orgs.org.id else orgs.other.id,
            label=label,
            provider_key=PROVIDER,
            verifier_key=VERIFIER,
            provider_connection_id=None,
        )
        db.commit()
        return row.id, secret


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(receiver_router)
    app.include_router(admin_router)

    def session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user=user
    )
    client = TestClient(app)
    client.headers["X-Organization-ID"] = str(organization.id)
    return client


def _event(
    event_id: str = "evt_1", event_type: str = "lead.created", data: dict | None = None
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "occurred_at": "2026-11-05T10:00:00Z",
            "data": data if data is not None else {"lead_ref": "L-1"},
        }
    ).encode("utf-8")


def _sign(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(
        secret.encode("utf-8"), stamp.encode("ascii") + b"." + body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Dealsflo-Timestamp": stamp,
        "X-Dealsflo-Signature": f"sha256={digest}",
        "Content-Type": "application/json",
    }


def _post(endpoint_id, body: bytes, headers: dict[str, str]):
    app_client = TestClient(_receiver_app())
    return app_client.post(
        f"/api/v1/webhooks/inbound/{endpoint_id}", content=body, headers=headers
    )


def _receiver_app() -> FastAPI:
    app = FastAPI()
    app.include_router(receiver_router)

    def session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = session
    return app


def _deliveries(endpoint_id) -> list[InboundWebhookDelivery]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(InboundWebhookDelivery)
            .where(InboundWebhookDelivery.endpoint_id == endpoint_id)
            .order_by(InboundWebhookDelivery.received_at)
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def _outbox_for(organization_id, key: str) -> list[OutboxEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.organization_id == organization_id,
                    OutboxEvent.idempotency_key == key,
                )
            ).all()
        )


def _audit_actions(organization_id) -> list[str]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.organization_id == organization_id,
                    AuditEvent.event_type == service.AUDIT_EVENT,
                )
            ).all()
        )


# --- verifier contract and synthetic format ----------------------------------------------------------


def test_the_synthetic_format_matches_its_documented_vector():
    body = b'{"id":"evt_1"}'
    expected = hmac.new(
        b"secret-value", b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    result = HmacSha256Verifier().verify(
        secret=ProviderSecret("secret-value"),
        timestamp_header="1700000000",
        signature_header=f"sha256={expected}",
        body=body,
        now_epoch=1700000010,
        replay_window_seconds=300,
    )
    assert result.verified is True


def test_the_signature_comparison_is_constant_time(monkeypatch):
    calls: list[tuple] = []
    real = hmac.compare_digest

    def spy(left, right):
        calls.append((left, right))
        return real(left, right)

    monkeypatch.setattr("app.webhooks.verifier.hmac.compare_digest", spy)
    HmacSha256Verifier().verify(
        secret=ProviderSecret("s"),
        timestamp_header=str(int(time.time())),
        signature_header="sha256=00",
        body=b"{}",
        now_epoch=int(time.time()),
        replay_window_seconds=300,
    )
    assert calls, "the verifier must compare with hmac.compare_digest"


@pytest.mark.parametrize(
    ("timestamp", "signature_prefix", "expected"),
    [
        (None, "sha256=", "missing_timestamp"),
        ("not-a-number", "sha256=", "malformed_timestamp"),
        ("1" * 25, "sha256=", "malformed_timestamp"),
        ("1700000000", "md5=", "malformed_signature"),
    ],
)
def test_the_verifier_names_malformed_headers(timestamp, signature_prefix, expected):
    result = HmacSha256Verifier().verify(
        secret=ProviderSecret("s"),
        timestamp_header=timestamp,
        signature_header=f"{signature_prefix}abcd",
        body=b"{}",
        now_epoch=1700000000,
        replay_window_seconds=300,
    )
    assert result.reason == expected


def test_a_missing_signature_is_refused_before_anything_else():
    result = HmacSha256Verifier().verify(
        secret=ProviderSecret("s"),
        timestamp_header="1700000000",
        signature_header=None,
        body=b"{}",
        now_epoch=1700000000,
        replay_window_seconds=300,
    )
    assert result.reason == "missing_signature"


# --- ingress: signatures, timestamps and tampering ---------------------------------------------------


def test_a_valid_signed_delivery_is_accepted_and_queued_once(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_valid")
    response = _post(endpoint_id, body, _sign(secret, body))

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted" and "organization_id" not in payload
    rows = _deliveries(endpoint_id)
    assert [row.outcome for row in rows] == ["accepted"]
    accepted = rows[0]
    assert accepted.organization_id == orgs.org.id
    assert (
        accepted.signature_verified is True
        and accepted.provider_event_id == "evt_valid"
    )
    assert (
        accepted.envelope["correlation_id"]
        == payload["correlation_id"]
        == accepted.correlation_id
    )
    assert (
        accepted.envelope["provider"] == PROVIDER
        and accepted.envelope["event_type"] == "lead.created"
    )
    assert (
        len(_outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_valid")) == 1
    )


def test_an_invalid_signature_is_refused_and_nothing_is_queued(orgs):
    endpoint_id, _secret = _endpoint(orgs)
    body = _event("evt_forged")
    response = _post(endpoint_id, body, _sign("wrong-secret", body))

    assert (
        response.status_code == 401 and response.json()["reason"] == "invalid_signature"
    )
    rows = _deliveries(endpoint_id)
    assert [row.outcome for row in rows] == ["rejected"]
    assert rows[0].envelope is None and rows[0].signature_verified is False
    assert _outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_forged") == []


def test_a_tampered_payload_fails_verification(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_tampered", data={"amount": 10})
    headers = _sign(secret, body)
    tampered = body.replace(b'"amount": 10', b'"amount": 99')
    response = _post(endpoint_id, tampered, headers)

    assert (
        response.status_code == 401 and response.json()["reason"] == "invalid_signature"
    )
    assert _outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_tampered") == []


@pytest.mark.parametrize(
    ("headers_for", "reason"),
    [
        (
            lambda secret, body: {"X-Dealsflo-Timestamp": str(int(time.time()))},
            "missing_signature",
        ),
        (
            lambda secret, body: {
                **_sign(secret, body),
                "X-Dealsflo-Signature": "md5=abc",
            },
            "malformed_signature",
        ),
        (
            lambda secret, body: {
                k: v
                for k, v in _sign(secret, body).items()
                if k != "X-Dealsflo-Timestamp"
            },
            "missing_timestamp",
        ),
        (
            lambda secret, body: {
                **_sign(secret, body),
                "X-Dealsflo-Timestamp": "soon",
            },
            "malformed_timestamp",
        ),
    ],
)
def test_missing_or_malformed_headers_are_refused(orgs, headers_for, reason):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_headers")
    response = _post(endpoint_id, body, headers_for(secret, body))
    assert response.status_code == 401 and response.json()["reason"] == reason
    assert _outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_headers") == []


def test_a_stale_signed_timestamp_is_refused_and_a_future_one_too(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_time")
    stale = _post(
        endpoint_id, body, _sign(secret, body, timestamp=int(time.time()) - 3600)
    )
    future = _post(
        endpoint_id, body, _sign(secret, body, timestamp=int(time.time()) + 600)
    )
    assert stale.json()["reason"] == "stale_timestamp"
    assert future.json()["reason"] == "future_timestamp"
    assert [row.outcome for row in _deliveries(endpoint_id)] == ["rejected", "rejected"]


def test_the_replay_window_is_configurable(orgs, monkeypatch):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_window")
    monkeypatch.setenv("INBOUND_WEBHOOK_REPLAY_WINDOW_SECONDS", "30")
    get_settings.cache_clear()
    try:
        response = _post(
            endpoint_id, body, _sign(secret, body, timestamp=int(time.time()) - 60)
        )
    finally:
        get_settings.cache_clear()
    assert response.json()["reason"] == "stale_timestamp"


def test_a_signature_for_one_endpoint_does_not_open_another(orgs):
    _first_id, first_secret = _endpoint(orgs, label="First")
    second_id, _second_secret = _endpoint(orgs, label="Second")
    body = _event("evt_cross")
    response = _post(second_id, body, _sign(first_secret, body))
    assert response.status_code == 401


# --- duplicates, replays and conflicts -----------------------------------------------------------------


def test_a_replayed_delivery_is_a_duplicate_and_is_not_queued_twice(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_replay")
    headers = _sign(secret, body)
    first = _post(endpoint_id, body, headers)
    second = _post(endpoint_id, body, headers)

    assert first.status_code == 202
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    outcomes = [row.outcome for row in _deliveries(endpoint_id)]
    assert outcomes == ["accepted", "duplicate"]
    assert (
        len(_outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_replay")) == 1
    )


def test_the_same_event_id_with_a_different_body_is_a_conflict(orgs):
    endpoint_id, secret = _endpoint(orgs)
    original = _event("evt_conflict", data={"lead_ref": "A"})
    changed = _event("evt_conflict", data={"lead_ref": "B"})
    assert _post(endpoint_id, original, _sign(secret, original)).status_code == 202
    response = _post(endpoint_id, changed, _sign(secret, changed))

    assert (
        response.status_code == 409
        and response.json()["reason"] == "conflicting_payload"
    )
    outcomes = [row.outcome for row in _deliveries(endpoint_id)]
    assert outcomes == ["accepted", "conflict"]
    accepted = _deliveries(endpoint_id)[0]
    assert accepted.envelope["payload"] == {"lead_ref": "A"}


def test_the_same_provider_event_id_on_two_endpoints_is_two_independent_deliveries(
    orgs,
):
    first_id, first_secret = _endpoint(orgs, label="First")
    second_id, second_secret = _endpoint(orgs, label="Second")
    body = _event("evt_shared_id")
    assert _post(first_id, body, _sign(first_secret, body)).status_code == 202
    assert _post(second_id, body, _sign(second_secret, body)).status_code == 202


# --- organization isolation ----------------------------------------------------------------------------


def test_another_organization_cannot_see_rotate_or_disable_an_endpoint(orgs):
    endpoint_id, secret = _endpoint(orgs)
    other = _client(orgs.other, orgs.other_org)
    assert all(
        item["id"] != str(endpoint_id)
        for item in other.get("/api/v1/webhook-endpoints").json()["items"]
    )
    assert (
        other.post(f"/api/v1/webhook-endpoints/{endpoint_id}/rotate").status_code == 404
    )
    assert (
        other.post(f"/api/v1/webhook-endpoints/{endpoint_id}/disable").status_code
        == 404
    )
    body = _event("evt_still_works")
    assert _post(endpoint_id, body, _sign(secret, body)).status_code == 202


def test_a_delivery_is_recorded_under_the_endpoints_organization_only(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_org", data={"organization_id": str(orgs.other_org.id)})
    assert _post(endpoint_id, body, _sign(secret, body)).status_code == 202
    row = _deliveries(endpoint_id)[0]
    assert row.organization_id == orgs.org.id
    assert "organization_id" not in row.envelope and "organization" not in row.envelope


def test_an_unknown_endpoint_is_not_found_without_a_record(orgs):
    body = _event("evt_unknown")
    response = _post(uuid.uuid4(), body, _sign("anything", body))
    assert (
        response.status_code == 404
        and response.json()["reason"] == "endpoint_not_found"
    )


# --- disabled endpoints and secrets -------------------------------------------------------------------


def test_a_disabled_endpoint_refuses_deliveries_and_destroys_its_secret(orgs):
    endpoint_id, secret = _endpoint(orgs)
    admin = _client(orgs.owner, orgs.org)
    assert (
        admin.post(f"/api/v1/webhook-endpoints/{endpoint_id}/disable").status_code
        == 200
    )
    body = _event("evt_disabled")
    response = _post(endpoint_id, body, _sign(secret, body))

    assert (
        response.status_code == 403 and response.json()["reason"] == "endpoint_disabled"
    )
    with SessionLocal() as db:
        row = db.get(InboundWebhookEndpoint, endpoint_id)
        assert (
            row.status == "disabled"
            and row.secret_ciphertext is None
            and row.secret_key_id is None
        )


def test_the_signing_secret_is_never_stored_in_plain_text(orgs):
    endpoint_id, secret = _endpoint(orgs)
    with SessionLocal() as db:
        row = db.get(InboundWebhookEndpoint, endpoint_id)
        assert secret not in (row.secret_ciphertext or "")
        assert secret not in repr(vars(row))


def test_rotation_replaces_the_secret_and_the_old_one_stops_working(orgs):
    endpoint_id, old_secret = _endpoint(orgs)
    admin = _client(orgs.owner, orgs.org)
    rotated = admin.post(f"/api/v1/webhook-endpoints/{endpoint_id}/rotate")
    assert rotated.status_code == 200
    new_secret = rotated.json()["signing_secret"]
    assert new_secret != old_secret and rotated.json()["secret_shown_once"] is True

    body = _event("evt_rotated")
    assert _post(endpoint_id, body, _sign(old_secret, body)).status_code == 401
    assert _post(endpoint_id, body, _sign(new_secret, body)).status_code == 202


def test_an_unreadable_secret_fails_closed_and_is_recorded_for_retry(orgs, monkeypatch):
    endpoint_id, secret = _endpoint(orgs)
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"other-key": _key()}))
    get_settings.cache_clear()
    try:
        body = _event("evt_no_key")
        response = _post(endpoint_id, body, _sign(secret, body))
    finally:
        get_settings.cache_clear()

    assert (
        response.status_code == 503
        and response.json()["reason"] == "secret_unavailable"
    )
    assert [row.outcome for row in _deliveries(endpoint_id)] == ["failed"]
    assert _outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_no_key") == []


# --- malformed payloads -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"{not json", "invalid_json"),
        (b"[1, 2]", "not_an_object"),
        (b'{"type": "lead.created", "data": {}}', "malformed_event_id"),
        (b'{"id": "evt", "type": "Lead Created"}', "malformed_event_type"),
        (b'{"id": "evt", "type": "lead.created", "data": "text"}', "malformed_data"),
        (
            b'{"id": "evt", "type": "lead.created", "occurred_at": "yesterday"}',
            "malformed_occurred_at",
        ),
        (b'{"id": "evt", "id": "evt2", "type": "lead.created"}', "duplicate_key"),
    ],
)
def test_malformed_payloads_are_refused_and_their_bytes_are_not_stored(
    orgs, body, reason
):
    endpoint_id, secret = _endpoint(orgs)
    response = _post(endpoint_id, body, _sign(secret, body))
    assert response.status_code == 400 and response.json()["reason"] == reason
    row = _deliveries(endpoint_id)[0]
    assert row.outcome == "rejected" and row.reason_code == reason
    assert row.signature_verified is True and row.envelope is None


def test_an_oversized_body_is_refused_before_it_is_read(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = b"{" + b" " * (MAX_BODY_BYTES + 10)
    response = _post(endpoint_id, body, _sign(secret, body))
    assert response.status_code == 413
    assert _deliveries(endpoint_id) == []


def test_the_envelope_parser_accepts_only_the_documented_shape():
    event = normalize(_event("evt_ok", data={"a": 1}))
    assert event.provider_event_id == "evt_ok" and event.payload == {"a": 1}
    with pytest.raises(MalformedWebhook):
        normalize(b"")


# --- redaction -----------------------------------------------------------------------------------------


def test_secrets_and_personal_values_are_redacted_before_they_are_stored(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event(
        "evt_pii",
        data={
            "api_key": "sk-live-1234567890",
            "card_number": "4111111111111111",
            "contact": {"email": "asha@example.test", "phone": "+91 98765 43210"},
            "note": "Call asha@example.test or +91 98765 43210 tomorrow.",
        },
    )
    assert _post(endpoint_id, body, _sign(secret, body)).status_code == 202
    row = _deliveries(endpoint_id)[0]
    stored = json.dumps(row.envelope)
    assert "sk-live-1234567890" not in stored and "4111111111111111" not in stored
    assert "asha@example.test" not in stored and "98765 43210" not in stored
    assert row.envelope["payload"]["api_key"] == "[REDACTED]"
    assert row.envelope["payload"]["contact"]["phone"] == "***3210"
    assert "[EMAIL]" in row.envelope["payload"]["note"]


def test_redaction_is_applied_to_nested_lists_and_long_strings():
    payload = redact_payload(
        {"items": [{"password": "x", "text": "a" * 2000}], "token": "t"}
    )
    assert payload["items"][0]["password"] == "[REDACTED]"
    assert len(payload["items"][0]["text"]) == 500
    assert payload["token"] == "[REDACTED]"


def test_audit_and_outbox_hold_identifiers_only(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_audit", data={"api_key": "sk-live-AUDITSECRET"})
    assert _post(endpoint_id, body, _sign(secret, body)).status_code == 202
    assert (
        _post(
            endpoint_id,
            _event("evt_forged_audit"),
            _sign("bad", _event("evt_forged_audit")),
        ).status_code
        == 401
    )

    with SessionLocal() as db:
        audit = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == orgs.org.id,
                AuditEvent.event_type == service.AUDIT_EVENT,
            )
        ).all()
        assert audit and all(
            "AUDITSECRET" not in str(row.event_metadata) for row in audit
        )
        assert all(secret not in str(row.event_metadata) for row in audit)
        outbox = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == orgs.org.id,
                OutboxEvent.event_type == service.RECEIVED_EVENT_TYPE,
            )
        ).all()
        assert outbox and all(
            "AUDITSECRET" not in json.dumps(row.payload) for row in outbox
        )
        assert all(set(row.payload) == {"delivery_id"} for row in outbox)
    actions = _audit_actions(orgs.org.id)
    assert "delivery_accepted" in actions and "delivery_rejected" in actions


# --- outbox handoff and idempotency -------------------------------------------------------------------


def _outbox_event(organization_id, payload) -> SimpleNamespace:
    return SimpleNamespace(organization_id=organization_id, payload=payload)


def test_the_outbox_handler_marks_a_delivery_handled_once(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_handled")
    response = _post(endpoint_id, body, _sign(secret, body))
    delivery_id = response.json()["delivery_id"]

    with SessionLocal() as db:
        service.handle_delivery_received(
            db, _outbox_event(orgs.org.id, {"delivery_id": delivery_id})
        )
        db.commit()
    first = _deliveries(endpoint_id)[0].handled_at
    with SessionLocal() as db:
        service.handle_delivery_received(
            db, _outbox_event(orgs.org.id, {"delivery_id": delivery_id})
        )
        db.commit()
    assert first is not None and _deliveries(endpoint_id)[0].handled_at == first


def test_the_handler_refuses_a_missing_delivery_permanently(orgs):
    with SessionLocal() as db, pytest.raises(PermanentHandlerError) as missing:
        service.handle_delivery_received(
            db, _outbox_event(orgs.org.id, {"delivery_id": str(uuid.uuid4())})
        )
    assert missing.value.reason_code == "delivery_not_found"
    with SessionLocal() as db, pytest.raises(PermanentHandlerError) as invalid:
        service.handle_delivery_received(
            db, _outbox_event(orgs.org.id, {"delivery_id": "not-a-uuid"})
        )
    assert invalid.value.reason_code == "invalid_delivery_payload"


def test_the_handler_is_registered_with_the_shared_outbox_and_registration_is_repeatable():
    from app.outbox.service import registered_event_types

    register_webhook_handlers()
    register_webhook_handlers()
    assert service.RECEIVED_EVENT_TYPE in registered_event_types()


def test_the_queued_event_is_keyed_so_a_repeat_cannot_queue_a_second_copy(orgs):
    endpoint_id, secret = _endpoint(orgs)
    body = _event("evt_keyed")
    headers = _sign(secret, body)
    for _ in range(3):
        _post(endpoint_id, body, headers)
    assert (
        len(_outbox_for(orgs.org.id, f"inbound_webhook:{endpoint_id}:evt_keyed")) == 1
    )


# --- administration -----------------------------------------------------------------------------------


def test_only_a_member_with_the_manage_permission_can_create_an_endpoint(orgs):
    body = {"label": "CRM", "provider_key": PROVIDER, "verifier_key": VERIFIER}
    assert (
        _client(orgs.owner, orgs.org)
        .post("/api/v1/webhook-endpoints", json=body)
        .status_code
        == 201
    )
    response = _client(orgs.reader, orgs.org).post(
        "/api/v1/webhook-endpoints", json=body
    )
    assert response.status_code == 403


def test_creation_refuses_unknown_verifiers_and_unconnected_connections(orgs):
    client = _client(orgs.owner, orgs.org)
    unknown = client.post(
        "/api/v1/webhook-endpoints",
        json={"label": "x", "provider_key": PROVIDER, "verifier_key": "md5_plain"},
    )
    assert (
        unknown.status_code == 422
        and unknown.json()["detail"]["reason"] == "unsupported_verifier"
    )
    unlinked = client.post(
        "/api/v1/webhook-endpoints",
        json={
            "label": "x",
            "provider_key": PROVIDER,
            "verifier_key": VERIFIER,
            "provider_connection_id": str(uuid.uuid4()),
        },
    )
    assert (
        unlinked.status_code == 422
        and unlinked.json()["detail"]["reason"] == "connection_not_connected"
    )


def test_the_list_never_shows_a_secret(orgs):
    _endpoint(orgs)
    body = _client(orgs.owner, orgs.org).get("/api/v1/webhook-endpoints").json()
    assert body["items"] and all("signing_secret" not in item for item in body["items"])
    assert all("secret_ciphertext" not in item for item in body["items"])


def test_the_secret_is_returned_once_at_creation(orgs):
    response = _client(orgs.owner, orgs.org).post(
        "/api/v1/webhook-endpoints",
        json={"label": "x", "provider_key": PROVIDER, "verifier_key": VERIFIER},
    )
    assert response.status_code == 201
    assert (
        response.json()["signing_secret"]
        and response.json()["secret_shown_once"] is True
    )
