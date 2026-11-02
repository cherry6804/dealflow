"""Provider connection lifecycle, API, policy gate, concurrency and secret safety (E06 WS4, ADR-0032).

A stub adapter stands in for the provider in every test that reaches the verification handler. It
is defined in this file only and is never registered in application code. No test uses a fake
provider response to claim real connectivity. Live provider verification is covered by the
real-adapter tests with a mock HTTP transport, which never reach the internet.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.provider_connections import canonical_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.base import Base
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.outbox_event import OutboxEvent
from app.db.models.outbox_replay_record import OutboxReplayRecord
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.db.models.provider_verification_attempt import ProviderVerificationAttempt
from app.db.session import SessionLocal, engine, get_db_session
from app.governance.capabilities import AI_MASTER
from app.governance.policy import (
    REASON_EXECUTION_GATES_PENDING,
    REASON_PROVIDER_NOT_CONNECTED,
    evaluate_capability,
)
from app.governance.service import set_capability_enabled
from app.outbox.service import dispatch_due_events
from app.provider_secrets.service import (
    revoke_provider_credential,
    rotate_provider_credential,
)
from app.providers import verification as verification_module
from app.providers.base import VerificationOutcome, VerificationResult
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.readiness import ReadinessCode, connection_readiness
from app.providers.service import (
    PROVIDER_VERIFICATION_EVENT,
    create_connection,
    rotate_connection_secret,
    schedule_due_verifications,
)
from app.providers.verification import register_provider_handlers
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

BASE = "/api/v1/ai"
NOW = datetime.now(UTC)
SECRET_PREFIX = "sk-ws4-test-"
CAPABILITY = "ai.assistant"


@dataclass
class StubAdapter:
    """Test-only adapter. Each call consumes the next scripted outcome; the last one repeats."""

    outcomes: list[VerificationOutcome]
    reasons: list[str | None] = field(default_factory=list)
    provider_key: str = "openai"
    adapter_version: str = "stub-v1"
    calls: list[str] = field(default_factory=list)

    def verify(self, api_key: str) -> VerificationResult:
        self.calls.append(api_key)
        index = min(len(self.calls) - 1, len(self.outcomes) - 1)
        reason = self.reasons[index] if index < len(self.reasons) else None
        return VerificationResult(
            outcome=self.outcomes[index],
            reason_code=reason,
            latency_ms=1,
            adapter_version=self.adapter_version,
        )


@pytest.fixture(autouse=True)
def provider_setup(monkeypatch) -> Iterator[None]:
    Base.metadata.create_all(bind=engine)
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "ws4-v1")
    monkeypatch.setenv(
        "PROVIDER_SECRETS_KEYRING",
        json.dumps({"ws4-v1": base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")}),
    )
    get_settings.cache_clear()
    register_provider_handlers()
    _wipe_outbox()
    yield
    _wipe_outbox()
    monkeypatch.undo()
    get_settings.cache_clear()


def _wipe_outbox() -> None:
    with SessionLocal() as db:
        db.execute(delete(OutboxReplayRecord))
        db.execute(delete(OutboxEvent))
        db.commit()


@pytest.fixture
def cleanup() -> Iterator[list[uuid.UUID]]:
    organizations: list[uuid.UUID] = []
    yield organizations
    with SessionLocal() as db:
        for organization_id in organizations:
            for model in (
                ProviderVerificationAttempt,
                ProviderConnection,
                ProviderCredential,
                OrganizationCapabilitySetting,
                AuditEvent,
            ):
                db.execute(delete(model).where(model.organization_id == organization_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
        db.commit()


class _StubSelector:
    def __init__(self) -> None:
        self.adapter: StubAdapter | None = None

    def set(self, adapter: StubAdapter) -> None:
        self.adapter = adapter


@pytest.fixture
def stub_adapter(monkeypatch) -> Iterator[_StubSelector]:
    """Route the verification handler to a test-only stub for the duration of one test."""
    selector = _StubSelector()
    monkeypatch.setattr(verification_module, "adapter_for", lambda provider_key: selector.adapter)
    yield selector


def _app(user) -> FastAPI:
    app = FastAPI()
    app.include_router(canonical_router)

    def override_db() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    return app


def _secret() -> str:
    return f"{SECRET_PREFIX}{uuid.uuid4().hex}"


def _run_worker(*, minutes: int = 5, days: int = 0):
    """Run one worker cycle at a time in the future, so retry delays have passed."""
    moment = datetime.now(UTC) + timedelta(minutes=minutes, days=days)
    with SessionLocal() as db:
        result = dispatch_due_events(db, worker_id="ws4-test", now=moment, batch_size=50)
        db.commit()
    return result


def _scheduled_cycle(*, days: int) -> None:
    """One worker cycle: queue due checks first, as the runtime does, then dispatch them."""
    moment = datetime.now(UTC) + timedelta(days=days, minutes=5)
    with SessionLocal() as db:
        schedule_due_verifications(db, now=moment)
        db.commit()
    with SessionLocal() as db:
        dispatch_due_events(db, worker_id="ws4-test", now=moment, batch_size=50)
        db.commit()


def _connection(organization_id: uuid.UUID) -> ProviderConnection:
    with SessionLocal() as db:
        row = db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == organization_id))
        db.expunge(row)
        return row


def _create_via_service(organization_id: uuid.UUID, actor_id: uuid.UUID, secret: str | None = None):
    with SessionLocal() as db:
        row = create_connection(
            db,
            organization_id=organization_id,
            actor_user_id=actor_id,
            provider_key="openai",
            label="Primary",
            secret=secret or _secret(),
        )
        db.commit()
        return row.id


def _ready(organization_id: uuid.UUID) -> ReadinessCode:
    with SessionLocal() as db:
        return connection_readiness(db, organization_id=organization_id, provider_key="openai").code


def _owner_client(user, organization_id: uuid.UUID) -> TestClient:
    client = TestClient(_app(user))
    client.headers.update({"X-Organization-ID": str(organization_id)})
    return client


# Lifecycle through the worker -------------------------------------------------------------


def test_create_queues_verification_and_never_reports_connected(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    secret = _secret()

    with _owner_client(owner, organization.id) as client:
        response = client.post(f"{BASE}/provider-connections",
                               json={"provider_key": "openai", "label": "Primary", "secret": secret})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "verifying"
    assert body["ready"] is False
    assert body["readiness_code"] == "verifying"
    assert secret not in response.text
    assert "ciphertext" not in response.text
    assert _ready(organization.id) is ReadinessCode.VERIFYING


def test_successful_verification_by_the_worker_makes_the_connection_ready(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    secret = _secret()
    _create_via_service(organization.id, owner.id, secret)
    adapter = StubAdapter([VerificationOutcome.SUCCEEDED])
    stub_adapter.set(adapter)

    result = _run_worker()

    assert result.delivered == 1
    assert adapter.calls == [secret]  # the adapter receives the stored secret, only inside the handler
    connection = _connection(organization.id)
    assert connection.status == ProviderConnection.STATUS_CONNECTED
    assert connection.verified_credential_version == 1
    assert connection.last_verified_at is not None
    assert _ready(organization.id) is ReadinessCode.READY
    with SessionLocal() as db:
        attempts = list(db.scalars(select(ProviderVerificationAttempt).where(
            ProviderVerificationAttempt.organization_id == organization.id)))
    assert [(a.outcome, a.trigger, a.credential_version) for a in attempts] == [("succeeded", "created", 1)]


def test_live_adapter_disabled_by_default_is_not_verified_and_never_connected(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)

    result = _run_worker()  # real adapter selection, live flag off

    assert result.delivered == 1
    connection = _connection(organization.id)
    assert connection.status == ProviderConnection.STATUS_UNVERIFIED
    assert connection.status_reason_code == "live_adapter_disabled"
    assert connection.next_verification_at is None
    assert _ready(organization.id) is ReadinessCode.NOT_VERIFIED
    with SessionLocal() as db:
        outcome = db.scalar(select(ProviderVerificationAttempt.outcome).where(
            ProviderVerificationAttempt.organization_id == organization.id))
    assert outcome == "not_verified"


def test_transient_failures_degrade_then_fail_after_the_threshold(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.TRANSIENT_FAILURE], reasons=["provider_unavailable"]))

    _run_worker(minutes=5, days=0)
    first = _connection(organization.id)
    assert first.status == ProviderConnection.STATUS_DEGRADED
    assert first.status_reason_code == "provider_unavailable"
    assert first.consecutive_failures == 1
    assert first.next_verification_at is not None
    assert _ready(organization.id) is ReadinessCode.DEGRADED

    _scheduled_cycle(days=1)
    _scheduled_cycle(days=2)  # third consecutive failure reaches the threshold
    failed = _connection(organization.id)
    assert failed.status == ProviderConnection.STATUS_FAILED
    assert failed.status_reason_code == "verification_failed_repeatedly"
    assert failed.next_verification_at is None
    assert _ready(organization.id) is ReadinessCode.FAILED


def test_permanent_rejection_fails_the_connection_without_scheduling_retries(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.PERMANENT_FAILURE], reasons=["provider_rejected_credential"]))

    _run_worker()

    connection = _connection(organization.id)
    assert connection.status == ProviderConnection.STATUS_FAILED
    assert connection.status_reason_code == "provider_rejected_credential"
    assert connection.next_verification_at is None


def test_timeout_is_recorded_as_a_transient_failure(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.TIMED_OUT], reasons=["verification_timed_out"]))

    _run_worker()

    connection = _connection(organization.id)
    assert connection.status == ProviderConnection.STATUS_DEGRADED
    assert connection.status_reason_code == "verification_timed_out"


def test_recovery_after_failure_requires_a_new_successful_verification(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.PERMANENT_FAILURE], reasons=["provider_rejected_credential"]))
    _run_worker()
    assert _connection(organization.id).status == ProviderConnection.STATUS_FAILED

    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    with _owner_client(owner, organization.id) as client:
        response = client.post(f"{BASE}/provider-connections/{connection_id}/verify")
    assert response.status_code == 202
    assert response.json()["status"] == "verifying"
    assert response.json()["ready"] is False

    _run_worker(minutes=10)
    assert _connection(organization.id).status == ProviderConnection.STATUS_CONNECTED
    assert _ready(organization.id) is ReadinessCode.READY


def test_rotation_makes_the_connection_not_ready_until_the_new_secret_is_verified(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    assert _ready(organization.id) is ReadinessCode.READY

    new_secret = _secret()
    with _owner_client(owner, organization.id) as client:
        response = client.post(f"{BASE}/provider-connections/{connection_id}/rotate",
                               json={"secret": new_secret})
    assert response.status_code == 200, response.text
    assert new_secret not in response.text
    assert response.json()["ready"] is False
    assert _ready(organization.id) is ReadinessCode.VERIFYING

    adapter = StubAdapter([VerificationOutcome.SUCCEEDED])
    stub_adapter.set(adapter)
    _run_worker(minutes=10)
    assert adapter.calls == [new_secret]
    connection = _connection(organization.id)
    assert connection.status == ProviderConnection.STATUS_CONNECTED
    assert connection.verified_credential_version == 2
    assert _ready(organization.id) is ReadinessCode.READY


def test_rotation_through_the_legacy_credential_route_is_detected_without_a_status_write(
    cleanup, stub_adapter
) -> None:
    """A rotation that bypasses the connection API must still make the connection not ready."""
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    assert _ready(organization.id) is ReadinessCode.READY

    connection = _connection(organization.id)
    with SessionLocal() as db:
        rotate_provider_credential(
            db,
            organization_id=organization.id,
            actor_user_id=owner.id,
            credential_id=connection.credential_id,
            secret=_secret(),
        )
        db.commit()

    assert _connection(organization.id).status == ProviderConnection.STATUS_CONNECTED  # unchanged row
    assert _ready(organization.id) is ReadinessCode.CREDENTIAL_CHANGED


def test_revocation_through_the_legacy_route_makes_the_connection_not_ready_and_fails_it(
    cleanup, stub_adapter
) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    connection = _connection(organization.id)
    with SessionLocal() as db:
        revoke_provider_credential(db, organization_id=organization.id, actor_user_id=owner.id,
                                   credential_id=connection.credential_id)
        db.commit()
    assert _ready(organization.id) is ReadinessCode.CREDENTIAL_REVOKED

    probe = StubAdapter([VerificationOutcome.SUCCEEDED])
    stub_adapter.set(probe)
    with SessionLocal() as db:
        schedule_due_verifications(db, now=datetime.now(UTC) + timedelta(days=2))
        db.commit()
    _run_worker(minutes=5, days=2)

    assert probe.calls == []  # a revoked credential is never sent to the provider
    failed = _connection(organization.id)
    assert failed.status == ProviderConnection.STATUS_FAILED
    assert failed.status_reason_code == "credential_revoked"


def test_disconnect_revokes_the_secret_and_is_idempotent(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()

    with _owner_client(owner, organization.id) as client:
        first = client.post(f"{BASE}/provider-connections/{connection_id}/disconnect")
        second = client.post(f"{BASE}/provider-connections/{connection_id}/disconnect")
        verify = client.post(f"{BASE}/provider-connections/{connection_id}/verify")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["status"] == "disconnected"
    assert verify.status_code == 409
    with SessionLocal() as db:
        credential = db.scalar(select(ProviderCredential).where(ProviderCredential.organization_id == organization.id))
    assert credential.status == "revoked"
    assert credential.ciphertext is None
    # No live connection remains, so the provider is not connected. The row keeps its disconnected status.
    assert _ready(organization.id) is ReadinessCode.NOT_CONNECTED
    assert _connection(organization.id).status == ProviderConnection.STATUS_DISCONNECTED


def test_a_superseded_check_is_skipped_without_a_provider_call(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    # Rotation queues a newer check; the older queued check must not run against the new version.
    with SessionLocal() as db:
        rotate_connection_secret(db, organization_id=organization.id, actor_user_id=owner.id,
                                 connection_id=connection_id, secret=_secret())
        db.commit()
    probe = StubAdapter([VerificationOutcome.SUCCEEDED])
    stub_adapter.set(probe)

    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="ws4-test", now=datetime.now(UTC) + timedelta(minutes=5), batch_size=50
        )
        db.commit()
    assert result.claimed == 2
    assert len(probe.calls) == 1  # only the check for the current version reaches the provider
    assert _connection(organization.id).verified_credential_version == 2


def test_verification_failure_leaves_no_secret_in_any_record_or_log(cleanup, stub_adapter, caplog) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    secret = _secret()
    _create_via_service(organization.id, owner.id, secret)
    stub_adapter.set(StubAdapter([VerificationOutcome.PERMANENT_FAILURE], reasons=["provider_rejected_credential"]))

    with caplog.at_level(logging.DEBUG):
        _run_worker()

    with SessionLocal() as db:
        attempts = db.scalars(select(ProviderVerificationAttempt)).all()
        audit = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization.id)).all()
        outbox = db.scalars(select(OutboxEvent)).all()
        connection = db.scalar(select(ProviderConnection))
        credential = db.scalar(select(ProviderCredential))
    stored = " ".join(
        [json.dumps(row.event_metadata or "") for row in audit]
        + [json.dumps(row.payload) for row in outbox]
        + [json.dumps(row.reason_code or "") + row.adapter_version for row in attempts]
        + [connection.label, connection.status_reason_code or ""]
        + [str(credential.ciphertext)]
    )
    assert secret not in stored
    assert SECRET_PREFIX not in stored
    assert secret not in caplog.text
    assert SECRET_PREFIX not in caplog.text


# Real adapter (mock transport only) --------------------------------------------------------


def _adapter(handler, *, live: bool = True) -> OpenAIAdapter:
    return OpenAIAdapter(live_enabled=live, timeout_seconds=5, transport=httpx.MockTransport(handler))


def test_openai_adapter_maps_provider_responses_to_stable_outcomes() -> None:
    def respond(status: int):
        return lambda request: httpx.Response(status, json={"error": "must not be stored"})

    assert _adapter(respond(200)).verify("k").outcome is VerificationOutcome.SUCCEEDED
    rejected = _adapter(respond(401)).verify("k")
    assert rejected.outcome is VerificationOutcome.PERMANENT_FAILURE
    assert rejected.reason_code == "provider_rejected_credential"
    assert _adapter(respond(429)).verify("k").outcome is VerificationOutcome.TRANSIENT_FAILURE
    assert _adapter(respond(503)).verify("k").reason_code == "provider_unavailable"
    assert _adapter(respond(418)).verify("k").reason_code == "unexpected_provider_response"


def test_openai_adapter_maps_network_failures_and_never_returns_a_body() -> None:
    def slow(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    def unreachable(request: httpx.Request):
        raise httpx.ConnectError("refused", request=request)

    timed_out = _adapter(slow).verify("k")
    assert timed_out.outcome is VerificationOutcome.TIMED_OUT
    assert timed_out.reason_code == "verification_timed_out"
    unavailable = _adapter(unreachable).verify("k")
    assert unavailable.outcome is VerificationOutcome.TRANSIENT_FAILURE
    assert unavailable.reason_code == "provider_unreachable"
    assert "refused" not in json.dumps(unavailable.__dict__)


def test_openai_adapter_with_live_access_disabled_never_contacts_the_network() -> None:
    def must_not_be_called(request: httpx.Request):
        raise AssertionError("live access is disabled but the adapter made a request")

    result = _adapter(must_not_be_called, live=False).verify("k")
    assert result.outcome is VerificationOutcome.NOT_VERIFIED
    assert result.reason_code == "live_adapter_disabled"


# Tenant isolation and permissions -------------------------------------------------------------


def test_cross_organization_access_to_a_connection_is_not_found(cleanup, stub_adapter) -> None:
    owner_a, org_a = create_owner_manager(permissions=("provider_credentials.manage",))
    owner_b, org_b = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.extend([org_a.id, org_b.id])
    connection_id = _create_via_service(org_a.id, owner_a.id)

    with _owner_client(owner_b, org_b.id) as client:
        assert client.get(f"{BASE}/provider-connections/{connection_id}").status_code == 404
        assert client.post(f"{BASE}/provider-connections/{connection_id}/verify").status_code == 404
        assert client.post(f"{BASE}/provider-connections/{connection_id}/rotate",
                           json={"secret": _secret()}).status_code == 404
        assert client.post(f"{BASE}/provider-connections/{connection_id}/disconnect").status_code == 404
        assert client.get(f"{BASE}/provider-connections/{connection_id}/attempts").status_code == 404
        listing = client.get(f"{BASE}/provider-connections")
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    assert listing.json()["can_manage"] is True
    assert _connection(org_a.id).status == ProviderConnection.STATUS_VERIFYING


def test_read_only_users_see_status_but_cannot_change_connections(cleanup) -> None:
    reader, organization = create_manager(permissions=("provider_credentials.read",))
    cleanup.append(organization.id)
    with _owner_client(reader, organization.id) as client:
        assert client.get(f"{BASE}/providers").status_code == 200
        listing = client.get(f"{BASE}/provider-connections")
        assert listing.status_code == 200
        assert listing.json()["can_manage"] is False
        create = client.post(f"{BASE}/provider-connections",
                             json={"provider_key": "openai", "label": "x", "secret": _secret()})
    assert create.status_code == 403


def test_users_without_the_read_permission_are_refused(cleanup) -> None:
    member, organization = create_manager(permissions=("deals.read",))
    cleanup.append(organization.id)
    with _owner_client(member, organization.id) as client:
        assert client.get(f"{BASE}/provider-connections").status_code == 403


def test_unauthenticated_requests_are_refused() -> None:
    with TestClient(_app(None)) as client:
        assert client.get(f"{BASE}/providers").status_code == 401


def test_providers_are_declared_but_not_executable(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.read",))
    cleanup.append(organization.id)
    with _owner_client(owner, organization.id) as client:
        items = client.get(f"{BASE}/providers").json()["items"]
    openai = next(item for item in items if item["key"] == "openai")
    assert openai["executable"] is False
    assert openai["adapter_implemented"] is True
    assert "text_generation" in openai["declared_operations"]


def test_attempt_history_is_listed_for_the_owning_organization(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    with _owner_client(owner, organization.id) as client:
        attempts = client.get(f"{BASE}/provider-connections/{connection_id}/attempts")
    assert attempts.status_code == 200
    items = attempts.json()["items"]
    assert len(items) == 1
    assert items[0]["outcome"] == "succeeded"
    assert "sk-" not in attempts.text


def test_api_validation_does_not_echo_the_secret(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    with _owner_client(owner, organization.id) as client:
        response = client.post(f"{BASE}/provider-connections",
                               json={"provider_key": "not-a-provider", "label": "x", "secret": "sk-short"})
    assert response.status_code in (400, 422)
    assert "sk-short" not in response.text


def test_a_second_live_connection_for_the_same_provider_is_refused(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    with _owner_client(owner, organization.id) as client:
        response = client.post(f"{BASE}/provider-connections",
                               json={"provider_key": "openai", "label": "Second", "secret": _secret()})
    assert response.status_code == 409


# Policy gate ----------------------------------------------------------------------------------


def _enable_ai(organization_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        for key in (AI_MASTER, CAPABILITY):
            set_capability_enabled(db, organization_id=organization_id, actor_user_id=actor_id,
                                   capability_key=key, is_enabled=True)
        db.commit()


def _decision(organization_id: uuid.UUID):
    with SessionLocal() as db:
        return evaluate_capability(db, organization_id=organization_id, capability_key=CAPABILITY)


def test_a_connected_provider_does_not_enable_ai_execution(cleanup, stub_adapter, monkeypatch) -> None:
    """Readiness, plus an entitled SIBVO snapshot, still leaves AI execution closed (WS5)."""
    from app.governance import org_entitlement
    from tests.test_org_entitlement_snapshot import KEY, KEY_ID, FakeSibvo, signed

    settings = get_settings().model_copy(update={
        "sibvo_org_snapshot_signing_key": SecretStr(KEY),
        "sibvo_org_snapshot_key_id": KEY_ID,
    })
    monkeypatch.setattr(org_entitlement, "get_settings", lambda: settings)
    sibvo = FakeSibvo()
    sibvo.answer = lambda org: signed(org, enabled=True)
    monkeypatch.setattr(org_entitlement, "fetch_organization_entitlements", sibvo)

    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    assert _ready(organization.id) is ReadinessCode.READY
    _enable_ai(organization.id, owner.id)

    decision = _decision(organization.id)

    assert decision.allowed is False
    assert decision.reason_code == REASON_EXECUTION_GATES_PENDING


def test_without_a_verified_connection_the_gate_fails_closed(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _enable_ai(organization.id, owner.id)
    decision = _decision(organization.id)
    assert decision.allowed is False
    assert decision.reason_code == REASON_PROVIDER_NOT_CONNECTED


def test_an_unverified_or_disconnected_connection_fails_the_gate_closed(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    _enable_ai(organization.id, owner.id)
    assert _decision(organization.id).reason_code == REASON_PROVIDER_NOT_CONNECTED  # verifying, not ready

    with SessionLocal() as db:
        from app.providers.service import disconnect_connection
        disconnect_connection(db, organization_id=organization.id, actor_user_id=owner.id, connection_id=connection_id)
        db.commit()
    assert _decision(organization.id).reason_code == REASON_PROVIDER_NOT_CONNECTED


def test_a_stale_verification_is_not_ready(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    with SessionLocal() as db:
        row = db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == organization.id))
        row.last_verified_at = datetime.now(UTC) - timedelta(days=30)
        db.commit()
    assert _ready(organization.id) is ReadinessCode.STALE


# Concurrency ------------------------------------------------------------------------------------


def test_two_checks_for_one_connection_run_one_after_the_other(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    connection_id = _create_via_service(organization.id, owner.id)
    with SessionLocal() as db:
        from app.providers.service import request_verification
        request_verification(db, organization_id=organization.id, actor_user_id=owner.id,
                             connection_id=connection_id)
        db.commit()

    class SlowAdapter(StubAdapter):
        def verify(self, api_key: str) -> VerificationResult:
            import time
            time.sleep(0.2)
            return super().verify(api_key)

    stub_adapter.set(SlowAdapter([VerificationOutcome.SUCCEEDED]))
    moment = datetime.now(UTC) + timedelta(minutes=5)
    errors: list[BaseException] = []

    def run(worker: str) -> None:
        try:
            with SessionLocal() as db:
                dispatch_due_events(db, worker_id=worker, now=moment, batch_size=1)
                db.commit()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(f"ws4-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert errors == []
    with SessionLocal() as db:
        attempts = db.scalars(select(ProviderVerificationAttempt).where(
            ProviderVerificationAttempt.organization_id == organization.id)).all()
    assert len(attempts) == 2  # the created check and the manual check, each run once
    connection = _connection(organization.id)
    assert connection.status == ProviderConnection.STATUS_CONNECTED
    assert connection.consecutive_failures == 0


def test_concurrent_creates_for_one_provider_yield_exactly_one_connection(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    outcomes: list[str] = []
    lock = threading.Lock()

    def create() -> None:
        try:
            _create_via_service(organization.id, owner.id)
            result = "created"
        except Exception as exc:  # noqa: BLE001 - the expected conflict type is checked below
            result = type(exc).__name__
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=create) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert outcomes.count("created") == 1
    assert len(outcomes) == 4
    with SessionLocal() as db:
        live = db.scalars(select(ProviderConnection).where(
            ProviderConnection.organization_id == organization.id,
            ProviderConnection.status != ProviderConnection.STATUS_DISCONNECTED)).all()
    assert len(live) == 1


def test_due_verification_sweeps_queue_each_check_once(cleanup, stub_adapter) -> None:
    owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    _create_via_service(organization.id, owner.id)
    stub_adapter.set(StubAdapter([VerificationOutcome.SUCCEEDED]))
    _run_worker()
    with SessionLocal() as db:
        row = db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == organization.id))
        row.next_verification_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    moment = datetime.now(UTC)
    with SessionLocal() as db:
        first = schedule_due_verifications(db, now=moment)
        db.commit()
    with SessionLocal() as db:
        second = schedule_due_verifications(db, now=moment)
        db.commit()
    assert first == 1
    assert second == 0
    with SessionLocal() as db:
        scheduled = db.scalars(select(OutboxEvent).where(
            OutboxEvent.organization_id == organization.id,
            OutboxEvent.event_type == PROVIDER_VERIFICATION_EVENT,
            OutboxEvent.payload["trigger"].as_string() == "scheduled")).all()
    assert len(scheduled) == 1
