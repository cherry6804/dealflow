"""Provider connection lifecycle, verification, readiness and the policy gate (ADR-0032).

Credentials are stored through the real encryption path. Verification is run through the real outbox handler.
Provider calls go through a mocked HTTP boundary (httpx MockTransport) or a stub adapter. No test contacts a real
provider, and live adapters stay off unless a test enables them against the mock transport.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.provider_connections import provider_connection_routes
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.outbox_event import OutboxEvent
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.db.models.provider_verification_attempt import ProviderVerificationAttempt
from app.db.session import SessionLocal, get_db_session
from app.errors import register_error_handlers
from app.governance.capabilities import AI_MASTER
from app.governance.policy import evaluate_capability
from app.governance.service import set_capability_enabled
from app.provider_secrets import service as secret_service
from app.provider_secrets.errors import ProviderSecretsConfigurationError
from app.provider_secrets.redaction import REDACTED
from app.provider_secrets.service import UnsupportedProviderError
from app.providers import service as connections
from app.providers.base import VerificationOutcome, VerificationResult
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.readiness import (
    ReadinessCode,
    any_provider_ready,
    connection_readiness,
)
from app.providers.verification import handle_verification_requested
from tests.governance_helpers import allow_organization_entitlements
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

PROVIDER = "openai"
SECRET_PREFIX = "sk-lifecycle-"


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def _secret() -> str:
    return f"{SECRET_PREFIX}{uuid.uuid4().hex}"


@pytest.fixture
def keyring(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "test-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"test-v1": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def org(keyring) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    user, organization = create_owner_manager(
        permissions=("provider_credentials.manage", "provider_credentials.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


def _cleanup(organization_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(ProviderVerificationAttempt).where(ProviderVerificationAttempt.organization_id == organization_id))
        db.execute(delete(ProviderConnection).where(ProviderConnection.organization_id == organization_id))
        db.execute(delete(ProviderCredential).where(ProviderCredential.organization_id == organization_id))
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


class StubAdapter:
    """A probe boundary that returns a fixed verification result and records the key it was given."""

    provider_key = PROVIDER
    adapter_version = "stub-v1"

    def __init__(self, result: VerificationResult) -> None:
        self.result = result
        self.received: list[str] = []

    def verify(self, api_key: str) -> VerificationResult:
        self.received.append(api_key)
        return self.result


def _result(outcome: VerificationOutcome, reason: str | None = None) -> VerificationResult:
    return VerificationResult(outcome=outcome, reason_code=reason, latency_ms=3, adapter_version="stub-v1")


def _use_adapter(monkeypatch, adapter) -> None:
    monkeypatch.setattr("app.providers.verification.adapter_for", lambda provider_key: adapter)


def _connect(organization_id: uuid.UUID, user_id: uuid.UUID, secret: str | None = None) -> uuid.UUID:
    with SessionLocal() as db:
        connection = connections.create_connection(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            provider_key=PROVIDER,
            label="Main",
            secret=secret or _secret(),
        )
        db.commit()
        return connection.id


def _verify(organization_id: uuid.UUID) -> None:
    """Run the newest queued verification through the real outbox handler."""
    with SessionLocal() as db:
        event = db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == connections.PROVIDER_VERIFICATION_EVENT,
            )
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
        )
        assert event is not None, "a verification must have been queued"
        handle_verification_requested(db, event)
        db.commit()


def _state(connection_id: uuid.UUID) -> ProviderConnection:
    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        assert row is not None
        db.expunge(row)
        return row


def _readiness(organization_id: uuid.UUID, connection_id: uuid.UUID | None = None):
    with SessionLocal() as db:
        return connection_readiness(db, organization_id=organization_id, provider_key=PROVIDER)


# --- Registration and the secret boundary -----------------------------------------------------------


def test_registration_stores_only_ciphertext_and_queues_one_check(org) -> None:
    organization_id, user_id = org
    secret = _secret()
    connection_id = _connect(organization_id, user_id, secret)

    state = _state(connection_id)
    assert state.status == ProviderConnection.STATUS_VERIFYING

    with SessionLocal() as db:
        credential = db.get(ProviderCredential, state.credential_id)
        assert credential is not None
        assert secret not in str(credential.ciphertext)
        queued = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == connections.PROVIDER_VERIFICATION_EVENT,
            )
        ).all()
        assert len(queued) == 1
        audit = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id)).all()
        for row in list(queued) + list(audit):
            text = json.dumps(
                {column.key: str(getattr(row, column.key)) for column in row.__table__.columns},
                default=str,
            )
            assert secret not in text


def test_unsupported_provider_and_a_second_live_connection_are_refused(org) -> None:
    organization_id, user_id = org
    _connect(organization_id, user_id)
    with SessionLocal() as db:
        with pytest.raises(connections.ConnectionConflictError):
            connections.create_connection(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                provider_key=PROVIDER,
                label="Second",
                secret=_secret(),
            )
        db.rollback()
        with pytest.raises(UnsupportedProviderError):
            connections.create_connection(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                provider_key="unknown-provider",
                label="Unknown",
                secret=_secret(),
            )
        db.rollback()


def test_creating_a_connection_without_a_key_configuration_writes_nothing(org, monkeypatch) -> None:
    organization_id, user_id = org
    monkeypatch.delenv("PROVIDER_SECRETS_KEYRING", raising=False)
    monkeypatch.delenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", raising=False)
    get_settings.cache_clear()
    with SessionLocal() as db:
        with pytest.raises(ProviderSecretsConfigurationError):
            connections.create_connection(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                provider_key=PROVIDER,
                label="No key",
                secret=_secret(),
            )
        db.rollback()
    with SessionLocal() as db:
        assert db.scalars(select(ProviderConnection).where(ProviderConnection.organization_id == organization_id)).all() == []
    get_settings.cache_clear()


# --- Verification outcomes -----------------------------------------------------------------------------


def test_a_successful_check_connects_and_makes_the_provider_ready(org, monkeypatch) -> None:
    organization_id, user_id = org
    adapter = StubAdapter(_result(VerificationOutcome.SUCCEEDED))
    _use_adapter(monkeypatch, adapter)
    connection_id = _connect(organization_id, user_id)

    _verify(organization_id)

    state = _state(connection_id)
    assert state.status == ProviderConnection.STATUS_CONNECTED
    assert state.verified_credential_version == 1
    assert state.last_verified_at is not None
    assert state.consecutive_failures == 0
    readiness = _readiness(organization_id)
    assert readiness.ready is True and readiness.code is ReadinessCode.READY
    with SessionLocal() as db:
        assert any_provider_ready(db, organization_id=organization_id, provider_keys=(PROVIDER,)) is True
        attempt = db.scalar(select(ProviderVerificationAttempt).where(ProviderVerificationAttempt.connection_id == connection_id))
        assert attempt is not None and attempt.outcome == "succeeded"
    # The adapter receives the key in memory only. It is not stored on the attempt.
    assert len(adapter.received) == 1 and adapter.received[0].startswith(SECRET_PREFIX)
    with SessionLocal() as db:
        stored = db.scalars(select(ProviderVerificationAttempt.reason_code)).all()
        assert all(value is None or REDACTED not in str(value) for value in stored)


def test_a_rejected_credential_fails_and_is_not_ready(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.PERMANENT_FAILURE, "provider_rejected_credential")))
    connection_id = _connect(organization_id, user_id)

    _verify(organization_id)

    state = _state(connection_id)
    assert state.status == ProviderConnection.STATUS_FAILED
    assert state.status_reason_code == "provider_rejected_credential"
    readiness = _readiness(organization_id)
    assert readiness.ready is False and readiness.code is ReadinessCode.FAILED


def test_transient_failures_degrade_then_fail_at_the_threshold(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.TRANSIENT_FAILURE, "provider_unavailable")))
    connection_id = _connect(organization_id, user_id)
    threshold = get_settings().provider_verification_failure_threshold

    for attempt in range(1, threshold):
        _verify(organization_id)
        state = _state(connection_id)
        assert state.consecutive_failures == attempt
        assert state.status == ProviderConnection.STATUS_DEGRADED
        assert _readiness(organization_id).ready is False

    _verify(organization_id)
    state = _state(connection_id)
    assert state.status == ProviderConnection.STATUS_FAILED
    assert state.status_reason_code == "verification_failed_repeatedly"
    assert state.next_verification_at is None


def test_a_timed_out_check_is_recorded_as_a_transient_failure(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.TIMED_OUT, "verification_timed_out")))
    connection_id = _connect(organization_id, user_id)

    _verify(organization_id)

    state = _state(connection_id)
    assert state.status == ProviderConnection.STATUS_DEGRADED
    assert state.status_reason_code == "verification_timed_out"
    with SessionLocal() as db:
        attempt = db.scalar(select(ProviderVerificationAttempt).where(ProviderVerificationAttempt.connection_id == connection_id))
        assert attempt is not None and attempt.outcome == "timed_out"


def test_checks_with_live_access_disabled_never_report_success(org, monkeypatch) -> None:
    """The default adapter does not contact the provider. Its answer is not verified, so nothing becomes ready."""
    organization_id, user_id = org
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(
        "app.providers.verification.adapter_for",
        lambda provider_key: OpenAIAdapter(
            live_enabled=False, timeout_seconds=5, transport=httpx.MockTransport(handler)
        ),
    )
    connection_id = _connect(organization_id, user_id)

    _verify(organization_id)

    assert calls == []
    state = _state(connection_id)
    assert state.status == ProviderConnection.STATUS_UNVERIFIED
    assert state.status_reason_code == "live_adapter_disabled"
    assert _readiness(organization_id).ready is False


def test_a_provider_without_an_adapter_is_recorded_and_never_ready(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, None)
    connection_id = _connect(organization_id, user_id)

    _verify(organization_id)

    state = _state(connection_id)
    # A missing adapter is a permanent condition, so the connection fails rather than degrading.
    assert state.status == ProviderConnection.STATUS_FAILED
    assert state.status_reason_code == "adapter_not_implemented"
    assert _readiness(organization_id).ready is False


# --- Readiness and freshness -----------------------------------------------------------------------------


def test_a_stale_verification_is_not_ready(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    old = datetime.now(UTC) - timedelta(hours=get_settings().provider_connection_freshness_hours + 1)
    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        row.last_verified_at = old
        db.commit()

    readiness = _readiness(organization_id)
    assert readiness.ready is False and readiness.code is ReadinessCode.STALE


def test_rotating_the_secret_stops_readiness_until_the_new_secret_is_verified(org, monkeypatch) -> None:
    organization_id, user_id = org
    adapter = StubAdapter(_result(VerificationOutcome.SUCCEEDED))
    _use_adapter(monkeypatch, adapter)
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    assert _readiness(organization_id).ready is True

    with SessionLocal() as db:
        connections.rotate_connection_secret(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            connection_id=connection_id,
            secret=_secret(),
        )
        db.commit()
    # Rotation puts the connection back to verifying, and readiness reports that state until the new secret passes.
    readiness = _readiness(organization_id)
    assert readiness.ready is False and readiness.code is ReadinessCode.VERIFYING

    _verify(organization_id)
    assert _readiness(organization_id).ready is True
    assert _state(connection_id).verified_credential_version == 2


def test_revoking_the_credential_makes_the_connection_not_ready(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    credential_id = _state(connection_id).credential_id

    with SessionLocal() as db:
        secret_service.revoke_provider_credential(
            db, organization_id=organization_id, actor_user_id=user_id, credential_id=credential_id
        )
        db.commit()

    readiness = _readiness(organization_id)
    assert readiness.ready is False and readiness.code is ReadinessCode.CREDENTIAL_REVOKED


def test_disconnecting_ends_the_connection_and_a_new_one_can_be_made(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)

    with SessionLocal() as db:
        first = connections.disconnect_connection(
            db, organization_id=organization_id, actor_user_id=user_id, connection_id=connection_id
        )
        db.commit()
        assert first.status == ProviderConnection.STATUS_DISCONNECTED
    with SessionLocal() as db:
        again = connections.disconnect_connection(
            db, organization_id=organization_id, actor_user_id=user_id, connection_id=connection_id
        )
        assert again.status == ProviderConnection.STATUS_DISCONNECTED
        db.rollback()

    readiness = _readiness(organization_id)
    assert readiness.ready is False and readiness.code is ReadinessCode.NOT_CONNECTED
    new_id = _connect(organization_id, user_id)
    assert new_id != connection_id


# --- Tenant isolation ---------------------------------------------------------------------------------------


def test_another_organization_cannot_read_change_or_use_a_connection(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    other_user, other_org = create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    try:
        with SessionLocal() as db:
            with pytest.raises(connections.ConnectionNotFoundError):
                connections.get_connection(db, organization_id=other_org.id, connection_id=connection_id)
            with pytest.raises(connections.ConnectionNotFoundError):
                connections.disconnect_connection(
                    db, organization_id=other_org.id, actor_user_id=other_user.id, connection_id=connection_id
                )
            db.rollback()
            assert any_provider_ready(db, organization_id=other_org.id, provider_keys=(PROVIDER,)) is False
        assert _state(connection_id).status == ProviderConnection.STATUS_CONNECTED
    finally:
        _cleanup(other_org.id)


# --- Policy gate integration -----------------------------------------------------------------------------


def test_the_policy_gate_denies_without_a_ready_provider_and_passes_to_the_next_gate_with_one(org, monkeypatch) -> None:
    organization_id, user_id = org
    allow_organization_entitlements(monkeypatch)
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    with SessionLocal() as db:
        for key in (AI_MASTER, "ai.assistant"):
            set_capability_enabled(db, organization_id=organization_id, actor_user_id=user_id, capability_key=key, is_enabled=True)
        db.commit()

    def decide() -> str:
        with SessionLocal() as db:
            decision = evaluate_capability(db, organization_id=organization_id, capability_key="ai.assistant")
            db.commit()
            return decision.reason_code

    assert decide() == "provider_not_connected"
    _connect(organization_id, user_id)
    assert decide() == "provider_not_connected"
    _verify(organization_id)
    # A ready provider satisfies the provider gate. The gates that are not built yet still deny.
    assert decide() == "execution_gates_pending"


# --- Permissions over the API -------------------------------------------------------------------------------


def _api_for(user) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(provider_connection_routes, prefix="/api/v1/ai")

    def override_session() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    return app


def test_a_read_only_user_can_list_but_cannot_create_a_connection(keyring) -> None:
    user, organization = create_manager(permissions=("provider_credentials.read",))
    try:
        with TestClient(_api_for(user)) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            listed = client.get("/api/v1/ai/provider-connections")
            created = client.post(
                "/api/v1/ai/provider-connections",
                json={"provider_key": PROVIDER, "label": "Main", "secret": _secret()},
            )
        assert listed.status_code == 200
        assert created.status_code == 403
    finally:
        _cleanup(organization.id)


def test_an_owner_creates_a_connection_through_the_api_without_echoing_the_secret(org, monkeypatch) -> None:
    organization_id, user_id = org
    secret = _secret()
    with TestClient(_api_for(_actor(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        created = client.post(
            "/api/v1/ai/provider-connections",
            json={"provider_key": PROVIDER, "label": "Main", "secret": secret},
        )
    assert created.status_code == 201, created.text
    assert secret not in created.text
    assert created.json()["status"] == ProviderConnection.STATUS_VERIFYING


def _actor(user_id: uuid.UUID):
    from app.db.models.user import User

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.expunge(user)
        return user


# --- The OpenAI adapter at the HTTP boundary -----------------------------------------------------------------


def _adapter(handler, *, live: bool = True) -> OpenAIAdapter:
    return OpenAIAdapter(live_enabled=live, timeout_seconds=5, transport=httpx.MockTransport(handler))


def test_adapter_success_and_rejection_map_to_stable_outcomes() -> None:
    seen: list[str] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"data": []})

    result = _adapter(ok).verify("sk-adapter-test")
    assert result.outcome is VerificationOutcome.SUCCEEDED and result.reason_code is None
    assert seen == ["Bearer sk-adapter-test"]
    assert "sk-adapter-test" not in repr(result)

    rejected = _adapter(lambda request: httpx.Response(401, text="sk-adapter-test is invalid")).verify("sk-adapter-test")
    assert rejected.outcome is VerificationOutcome.PERMANENT_FAILURE
    assert rejected.reason_code == "provider_rejected_credential"
    assert "sk-adapter-test" not in repr(rejected)


@pytest.mark.parametrize(
    ("status", "outcome", "reason"),
    [
        (429, VerificationOutcome.TRANSIENT_FAILURE, "provider_unavailable"),
        (503, VerificationOutcome.TRANSIENT_FAILURE, "provider_unavailable"),
        (404, VerificationOutcome.PERMANENT_FAILURE, "unexpected_provider_response"),
    ],
)
def test_adapter_status_codes_are_classified(status: int, outcome: VerificationOutcome, reason: str) -> None:
    result = _adapter(lambda request: httpx.Response(status)).verify("sk-x")
    assert result.outcome is outcome and result.reason_code == reason


def test_adapter_network_errors_and_timeouts_are_classified() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    unreachable = _adapter(refused).verify("sk-x")
    assert unreachable.outcome is VerificationOutcome.TRANSIENT_FAILURE
    assert unreachable.reason_code == "provider_unreachable"
    timed_out = _adapter(slow).verify("sk-x")
    assert timed_out.outcome is VerificationOutcome.TIMED_OUT
    assert timed_out.reason_code == "verification_timed_out"


def test_adapter_with_live_access_disabled_sends_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    result = _adapter(handler, live=False).verify("sk-x")
    assert calls == []
    assert result.outcome is VerificationOutcome.NOT_VERIFIED
