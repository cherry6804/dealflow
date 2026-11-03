"""SIBVO service contract (client) and the AI execution gate with the organization snapshot (WS5).

The client tests use an httpx mock transport, so they check exactly what Dealsflo sends and how it
reacts. They do not prove that SIBVO answers as described; the cross-repository contract run does.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.organization_entitlement_snapshot import (
    OrganizationEntitlementSnapshot,
)
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.db.session import SessionLocal
from app.governance import org_entitlement
from app.governance.ai_execution import (
    AiExecutionDenied,
    require_ai_execution,
)
from app.governance.capabilities import AI_MASTER
from app.governance.execution_gate import (
    AI_EXECUTION_EVENT_TYPE,
    GATE_ACTOR,
    REASON_SYSTEM_ACTOR_NOT_PERMITTED,
)
from app.governance.policy import (
    REASON_ENTITLEMENT_DISABLED,
    REASON_EXECUTION_GATES_PENDING,
    REASON_PROVIDER_NOT_CONNECTED,
    evaluate_capability,
)
from app.governance.service import set_capability_enabled
from app.integrations import sibvo_client
from app.integrations.sibvo_client import (
    SibvoInvalidResponse,
    SibvoRejected,
    SibvoRequestDenied,
    SibvoUnavailable,
    fetch_organization_entitlements,
)
from app.provider_secrets.service import create_provider_credential
from tests.governance_helpers import attested_user_context
from tests.test_org_entitlement_snapshot import KEY, KEY_ID, FakeSibvo, signed
from tests.test_team_api import create_owner_manager

CAPABILITY = "ai.assistant"
SIBVO_BASE = "http://sibvo.test/api/v1"


@pytest.fixture(autouse=True)
def reset_breaker():
    sibvo_client.breaker.reset()
    yield
    sibvo_client.breaker.reset()


@pytest.fixture
def client_settings(monkeypatch):
    settings = get_settings().model_copy(update={
        "sso_dealsflo_client_id": "dealsflo",
        "sso_dealsflo_client_secret": SecretStr("s" * 40),
        "sso_sibvo_base_url": SIBVO_BASE,
        "sso_http_timeout_seconds": 5,
        "sso_dealsflo_product_key": "dealsflo",
        "sibvo_org_snapshot_signing_key": SecretStr(KEY),
        "sibvo_org_snapshot_key_id": KEY_ID,
    })
    monkeypatch.setattr(org_entitlement, "get_settings", lambda: settings)
    return settings


def use_transport(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording)
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(sibvo_client.httpx, "Client", factory)
    return seen


# Client contract --------------------------------------------------------------------------------


def test_request_is_authenticated_posted_and_scoped_to_the_organization(monkeypatch, client_settings) -> None:
    org = uuid4()
    seen = use_transport(monkeypatch, lambda request: httpx.Response(200, json={"active": False}))

    fetch_organization_entitlements(client_settings, org)

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"{SIBVO_BASE}/sso/organization-entitlements"
    expected = base64.b64encode(f"dealsflo:{'s' * 40}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    assert request.headers.get("x-correlation-id")
    assert request.content.decode() == f"organization_id={org}"


def test_credentials_are_never_sent_in_the_url(monkeypatch, client_settings) -> None:
    seen = use_transport(monkeypatch, lambda request: httpx.Response(200, json={"active": False}))
    fetch_organization_entitlements(client_settings, uuid4())
    assert "s" * 40 not in str(seen[0].url)
    assert "dealsflo" not in str(seen[0].url)


def test_unauthorized_client_is_reported_as_rejected(monkeypatch, client_settings) -> None:
    use_transport(monkeypatch, lambda request: httpx.Response(401, json={"detail": "no"}))
    with pytest.raises(SibvoRejected):
        fetch_organization_entitlements(client_settings, uuid4())


def test_server_errors_are_retried_then_unavailable(monkeypatch, client_settings) -> None:
    seen = use_transport(monkeypatch, lambda request: httpx.Response(503))
    with pytest.raises(SibvoUnavailable):
        fetch_organization_entitlements(client_settings, uuid4())
    assert len(seen) == 2  # bounded: at most two attempts


def test_connection_failures_are_unavailable(monkeypatch, client_settings) -> None:
    def refuse(request: httpx.Request):
        raise httpx.ConnectError("refused", request=request)

    use_transport(monkeypatch, refuse)
    with pytest.raises(SibvoUnavailable):
        fetch_organization_entitlements(client_settings, uuid4())


def test_a_client_error_is_a_request_denial_not_a_grant(monkeypatch, client_settings) -> None:
    use_transport(monkeypatch, lambda request: httpx.Response(422, json={"error_code": "bad_request"}))
    with pytest.raises(SibvoRequestDenied):
        fetch_organization_entitlements(client_settings, uuid4())


def test_non_object_bodies_are_invalid(monkeypatch, client_settings) -> None:
    use_transport(monkeypatch, lambda request: httpx.Response(200, json=["not", "an", "object"]))
    with pytest.raises(SibvoInvalidResponse):
        fetch_organization_entitlements(client_settings, uuid4())


def test_missing_client_secret_is_unavailable_without_a_request(monkeypatch, client_settings) -> None:
    seen = use_transport(monkeypatch, lambda request: httpx.Response(200, json={"active": False}))
    settings = client_settings.model_copy(update={"sso_dealsflo_client_secret": None})
    with pytest.raises(SibvoUnavailable):
        fetch_organization_entitlements(settings, uuid4())
    assert seen == []


# Gate with the organization snapshot --------------------------------------------------------------


@pytest.fixture
def secrets_keyring(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "ws5-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({
        "ws5-v1": base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("="),
    }))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def sibvo(monkeypatch, client_settings) -> FakeSibvo:
    fake = FakeSibvo()
    monkeypatch.setattr(org_entitlement, "fetch_organization_entitlements", fake)
    return fake


@pytest.fixture
def org(secrets_keyring):
    with SessionLocal() as db:
        owner, organization = create_owner_manager(permissions=("provider_credentials.manage",))
        org_id, owner_id = organization.id, owner.id
        set_capability_enabled(db, organization_id=org_id, actor_user_id=owner_id,
                               capability_key=AI_MASTER, is_enabled=True)
        set_capability_enabled(db, organization_id=org_id, actor_user_id=owner_id,
                               capability_key=CAPABILITY, is_enabled=True)
        db.commit()
    yield org_id, owner
    with SessionLocal() as db:
        for model in (OrganizationEntitlementSnapshot, ProviderConnection, ProviderCredential,
                      OrganizationCapabilitySetting, AuditEvent):
            db.execute(delete(model).where(model.organization_id == org_id))
        db.commit()


def make_provider_ready(org_id, owner_id) -> None:
    with SessionLocal() as db:
        credential = create_provider_credential(
            db, organization_id=org_id, actor_user_id=owner_id, provider_key="openai",
            label="Primary", secret=f"sk-ws5-{uuid4().hex}",
        )
        db.flush()
        db.add(ProviderConnection(
            id=uuid4(), organization_id=org_id, provider_key="openai", credential_id=credential.id,
            label="Primary", status=ProviderConnection.STATUS_CONNECTED,
            verified_credential_version=credential.version, last_verified_at=datetime.now(UTC),
            consecutive_failures=0, version=1, created_by_user_id=owner_id,
        ))
        db.commit()


def decision(org_id):
    with SessionLocal() as db:
        result = evaluate_capability(db, organization_id=org_id, capability_key=CAPABILITY)
        db.commit()
        return result


def test_without_a_provider_the_gate_denies_and_never_calls_sibvo(org, sibvo) -> None:
    org_id, _ = org
    sibvo.answer = lambda o: signed(o, enabled=True)

    assert decision(org_id).reason_code == REASON_PROVIDER_NOT_CONNECTED
    assert sibvo.calls == []


def test_a_ready_provider_with_an_enabled_entitlement_is_still_not_executable(org, sibvo) -> None:
    """Readiness and entitlement are both necessary and neither is sufficient."""
    org_id, owner = org
    make_provider_ready(org_id, owner.id)
    sibvo.answer = lambda o: signed(o, enabled=True)

    result = decision(org_id)

    assert result.allowed is False
    assert result.reason_code == REASON_EXECUTION_GATES_PENDING
    assert len(sibvo.calls) == 1


def test_a_ready_provider_with_a_disabled_entitlement_is_denied(org, sibvo) -> None:
    org_id, owner = org
    make_provider_ready(org_id, owner.id)
    sibvo.answer = lambda o: signed(o, enabled=False)

    result = decision(org_id)

    assert result.allowed is False
    assert result.reason_code == REASON_ENTITLEMENT_DISABLED


def test_session_snapshot_cannot_grant_what_the_organization_snapshot_denies(org, sibvo) -> None:
    """The user's session says ai_gateway is on, but SIBVO's organization snapshot says off."""
    org_id, owner = org
    make_provider_ready(org_id, owner.id)
    sibvo.answer = lambda o: signed(o, enabled=False)
    user_context = attested_user_context(
        owner, organization_id=org_id,
        entitlements=[{"feature_key": "ai_gateway", "enabled": True, "limit_value": None, "limit_unit": None}],
    )

    with SessionLocal() as db:
        result = evaluate_capability(db, organization_id=org_id, capability_key=CAPABILITY,
                                     user_context=user_context)
        db.commit()

    assert result.allowed is False
    assert result.reason_code == REASON_ENTITLEMENT_DISABLED


def test_background_execution_is_refused_and_audited(org, sibvo) -> None:
    org_id, owner = org
    make_provider_ready(org_id, owner.id)
    sibvo.answer = lambda o: signed(o, enabled=True)

    with SessionLocal() as db:
        with pytest.raises(AiExecutionDenied) as denied:
            require_ai_execution(db, organization_id=org_id, capability_key=CAPABILITY,
                                 user_context=None, correlation_id="corr-ws5")
        db.commit()

    # WP4: a system actor is refused at the actor gate, before the policy's pending gate. Still denied and audited.
    assert denied.value.decision.gate == GATE_ACTOR
    assert denied.value.decision.reason_code == REASON_SYSTEM_ACTOR_NOT_PERMITTED
    with SessionLocal() as db:
        audit = db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == org_id,
            AuditEvent.event_type == AI_EXECUTION_EVENT_TYPE,
        )).all()
    assert len(audit) == 1
    assert audit[0].decision == "denied"
    metadata = json.loads(audit[0].event_metadata)
    assert metadata["reason_code"] == REASON_SYSTEM_ACTOR_NOT_PERMITTED
    assert metadata["gate"] == GATE_ACTOR


def test_audit_metadata_carries_no_plan_or_secret_data(org, sibvo) -> None:
    org_id, owner = org
    make_provider_ready(org_id, owner.id)
    sibvo.answer = lambda o: signed(o, enabled=True)
    with SessionLocal() as db:
        with pytest.raises(AiExecutionDenied):
            require_ai_execution(db, organization_id=org_id, capability_key=CAPABILITY)
        db.commit()
    with SessionLocal() as db:
        metadata = db.scalars(select(AuditEvent.event_metadata).where(
            AuditEvent.organization_id == org_id,
            AuditEvent.event_type == AI_EXECUTION_EVENT_TYPE,
        )).all()
    text = " ".join(metadata)
    assert "sk-" not in text
    assert "entitlements" not in text


def test_outage_after_expiry_denies_the_gate(org, sibvo, monkeypatch) -> None:
    org_id, owner = org
    make_provider_ready(org_id, owner.id)
    sibvo.answer = lambda o: signed(o, enabled=True)
    assert decision(org_id).reason_code == REASON_EXECUTION_GATES_PENDING
    sibvo.answer = SibvoUnavailable("SIBVO could not be reached.")
    with SessionLocal() as db:
        row = db.scalar(select(OrganizationEntitlementSnapshot).where(
            OrganizationEntitlementSnapshot.organization_id == org_id))
        # The stored snapshot has expired. Clearing it forces the refresh path, which SIBVO cannot serve.
        row.snapshot_body = None
        row.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        db.commit()

    result = decision(org_id)

    assert result.allowed is False
    assert result.reason_code == "snapshot_unavailable"
