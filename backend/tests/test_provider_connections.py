"""Provider connections: registry, secret boundary, verification, health age and gate integration (DFR1-006).

No provider is verified in production today: the probe registry is empty. These tests register test-only probes
to exercise the verification path. They never assert that a real provider is connected.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.provider_connection import ProviderConnection
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance import provider_connections
from app.governance.capabilities import CAPABILITY_BY_KEY, ancestry
from app.governance.policy import evaluate_capability
from app.governance.provider_connections import (
    ProbeFailedError,
    ProviderConnectionError,
    ProviderConnectionExistsError,
    create_connection,
    disable_connection,
    provider_gate,
    verify_connection,
)
from app.governance.service import set_capability_enabled
from tests.governance_helpers import attested_user_context
from tests.test_governance_api import _app_for
from tests.test_team_api import create_manager

BASE = "/api/v1/governance"
SECRET_NAME = "TEST_EMAIL_PROVIDER_SECRET"
SECRET_VALUE = "sk-test-value-never-returned-0123456789"


@pytest.fixture
def tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(
        permissions=("governance.providers.manage", "governance.providers.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


@pytest.fixture
def other_tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(
        permissions=("governance.providers.manage", "governance.providers.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(ProviderConnection).where(ProviderConnection.organization_id == organization_id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


def _actor(user_id: UUID) -> User:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.expunge(user)
        return user


def _create(organization_id: UUID, user_id: UUID, kind: str = "email", name: str = "Mail") -> UUID:
    with SessionLocal() as db:
        row = create_connection(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            provider_kind=kind,
            display_name=name,
            secret_ref=SECRET_NAME,
        )
        db.commit()
        return row.id


def _verify(organization_id: UUID, user_id: UUID, connection_id: UUID) -> tuple[str, str | None, datetime | None]:
    """Run verification and return the stored status, error code and verification time, read in-session."""
    with SessionLocal() as db:
        row = verify_connection(db, organization_id=organization_id, actor_user_id=user_id, connection_id=connection_id)
        snapshot = (row.status, row.last_error_code, row.last_verified_at)
        db.commit()
    return snapshot


def _gate(organization_id: UUID, provider_kind: str | None, now: datetime | None = None) -> str | None:
    with SessionLocal() as db:
        return provider_gate(db, organization_id=organization_id, provider_kind=provider_kind, now=now)


@pytest.fixture
def secret(monkeypatch) -> None:
    monkeypatch.setenv(SECRET_NAME, SECRET_VALUE)


@pytest.fixture
def success_probe(monkeypatch) -> list[str]:
    calls: list[str] = []

    def probe(secret_value: str) -> None:
        calls.append(secret_value)

    monkeypatch.setitem(provider_connections.PROBES, "email", probe)
    return calls


# --- Registry and validation -----------------------------------------------------------------------


def test_a_new_connection_starts_not_verified_and_is_audited(tenant, secret) -> None:
    organization_id, user_id = tenant
    connection_id = _create(organization_id, user_id)

    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        assert row is not None
        assert row.status == "not_verified"
        assert row.secret_ref == SECRET_NAME
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == "provider.connection.created",
            )
        )
        assert audit is not None


@pytest.mark.parametrize(
    ("kind", "secret_ref"),
    [("fax", SECRET_NAME), ("email", "lower_case_name"), ("email", "A")],
)
def test_invalid_kind_or_secret_reference_is_refused(tenant, kind, secret_ref) -> None:
    organization_id, user_id = tenant
    with SessionLocal() as db:
        with pytest.raises(ProviderConnectionError):
            create_connection(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                provider_kind=kind,
                display_name="Bad",
                secret_ref=secret_ref,
            )
        db.rollback()


def test_one_connection_per_kind_per_organization(tenant, secret) -> None:
    organization_id, user_id = tenant
    _create(organization_id, user_id)
    with SessionLocal() as db:
        with pytest.raises(ProviderConnectionExistsError):
            create_connection(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                provider_kind="email",
                display_name="Second",
                secret_ref=SECRET_NAME,
            )
        db.rollback()


# --- Secret boundary --------------------------------------------------------------------------------


def test_the_secret_value_is_never_stored_returned_or_audited(tenant, secret, success_probe) -> None:
    organization_id, user_id = tenant
    connection_id = _create(organization_id, user_id)
    _verify(organization_id, user_id, connection_id)

    with TestClient(_app_for(_actor(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        listed = client.get(f"{BASE}/providers")

    assert listed.status_code == 200
    assert SECRET_VALUE not in listed.text
    assert listed.json()[0]["secret_present"] is True
    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        assert row is not None
        stored = json.dumps({"secret_ref": row.secret_ref, "status": row.status, "error": row.last_error_code})
        audits = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id)).all()
        assert SECRET_VALUE not in stored
        assert all(SECRET_VALUE not in (audit.event_metadata or "") for audit in audits)


def test_a_missing_secret_is_reported_as_unhealthy_not_connected(tenant, monkeypatch) -> None:
    organization_id, user_id = tenant
    monkeypatch.delenv(SECRET_NAME, raising=False)
    connection_id = _create(organization_id, user_id)

    status, error_code, _verified_at = _verify(organization_id, user_id, connection_id)
    assert status == "unhealthy"
    assert error_code == "secret_missing"


# --- Verification ---------------------------------------------------------------------------------------


def test_without_a_registered_probe_nothing_is_verified(tenant, secret) -> None:
    organization_id, user_id = tenant
    connection_id = _create(organization_id, user_id)

    status, error_code, verified_at = _verify(organization_id, user_id, connection_id)
    assert status == "not_verified"
    assert error_code == "no_probe_available"
    assert verified_at is None


def test_a_successful_probe_verifies_and_a_failing_probe_records_only_its_code(
    tenant, secret, monkeypatch
) -> None:
    organization_id, user_id = tenant
    connection_id = _create(organization_id, user_id)

    def rejected(_value: str) -> None:
        raise ProbeFailedError("auth_rejected")

    monkeypatch.setitem(provider_connections.PROBES, "email", rejected)
    assert _verify(organization_id, user_id, connection_id)[:2] == ("unhealthy", "auth_rejected")

    def leaks(_value: str) -> None:
        raise RuntimeError(f"echoed {SECRET_VALUE}")

    monkeypatch.setitem(provider_connections.PROBES, "email", leaks)
    unexpected_status, unexpected_code, _ = _verify(organization_id, user_id, connection_id)
    assert unexpected_status == "unhealthy"
    assert unexpected_code == "probe_failed"
    assert SECRET_VALUE not in (unexpected_code or "")

    monkeypatch.setitem(provider_connections.PROBES, "email", lambda _value: None)
    status, error_code, verified_at = _verify(organization_id, user_id, connection_id)
    assert status == "verified"
    assert verified_at is not None
    assert error_code is None


# --- Gate check ------------------------------------------------------------------------------------------


def _verified(organization_id: UUID, user_id: UUID, monkeypatch, connection_id: UUID | None = None) -> UUID:
    monkeypatch.setitem(provider_connections.PROBES, "email", lambda _value: None)
    connection = connection_id or _create(organization_id, user_id)
    assert _verify(organization_id, user_id, connection)[0] == "verified"
    return connection


def test_a_fresh_verified_connection_satisfies_the_gate(tenant, secret, monkeypatch) -> None:
    organization_id, user_id = tenant
    _verified(organization_id, user_id, monkeypatch)
    assert _gate(organization_id, "email") is None


def test_a_stale_verification_needs_a_fresh_check(tenant, secret, monkeypatch) -> None:
    organization_id, user_id = tenant
    _verified(organization_id, user_id, monkeypatch)
    later = datetime.now(UTC) + timedelta(seconds=get_settings().provider_health_max_age_seconds + 60)
    assert _gate(organization_id, "email", now=later) == "provider_health_stale"


def test_removing_the_secret_after_verification_fails_closed(tenant, secret, monkeypatch) -> None:
    organization_id, user_id = tenant
    _verified(organization_id, user_id, monkeypatch)
    monkeypatch.delenv(SECRET_NAME)
    assert _gate(organization_id, "email") == "provider_unhealthy"


def test_a_disabled_or_unverified_connection_does_not_satisfy_the_gate(tenant, secret, monkeypatch) -> None:
    organization_id, user_id = tenant
    connection_id = _create(organization_id, user_id)
    assert _gate(organization_id, "email") == "provider_not_connected"

    _verified(organization_id, user_id, monkeypatch, connection_id)
    with SessionLocal() as db:
        disable_connection(db, organization_id=organization_id, actor_user_id=user_id, connection_id=connection_id)
        db.commit()
    assert _gate(organization_id, "email") == "provider_not_connected"


def test_a_capability_without_a_provider_kind_always_fails_closed(tenant, secret, monkeypatch) -> None:
    organization_id, user_id = tenant
    _verified(organization_id, user_id, monkeypatch)
    assert _gate(organization_id, None) == "provider_not_connected"


def test_the_policy_checks_the_provider_before_consent(tenant, secret, monkeypatch) -> None:
    organization_id, user_id = tenant
    original = CAPABILITY_BY_KEY["channels.email"]
    monkeypatch.setitem(CAPABILITY_BY_KEY, "channels.email", replace(original, entitlement_feature="channels_email"))
    with SessionLocal() as db:
        for definition in ancestry(CAPABILITY_BY_KEY["channels.email"]):
            set_capability_enabled(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                capability_key=definition.key,
                is_enabled=True,
            )
        db.commit()

    def decide() -> str:
        with SessionLocal() as db:
            context = attested_user_context(
                _actor(user_id),
                organization_id=organization_id,
                entitlements=[{"feature_key": "channels_email", "enabled": True}],
            )
            decision = evaluate_capability(
                db, organization_id=organization_id, capability_key="channels.email", user_context=context
            )
            db.commit()
            return decision.reason_code

    # No verified connection: the provider gate stops the capability before consent is considered.
    assert decide() == "provider_not_connected"
    _verified(organization_id, user_id, monkeypatch)
    # With a verified connection the provider gate passes, and consent is then required per contact.
    assert decide() == "consent_not_configured"


# --- Tenant isolation and permissions --------------------------------------------------------------------


def test_another_organization_cannot_see_or_change_a_connection(tenant, other_tenant, secret) -> None:
    organization_id, user_id = tenant
    connection_id = _create(organization_id, user_id)
    other_org, other_user = other_tenant

    with TestClient(_app_for(_actor(other_user))) as client:
        client.headers.update({"X-Organization-ID": str(other_org)})
        listed = client.get(f"{BASE}/providers")
        verified = client.post(f"{BASE}/providers/{connection_id}/verify")
        disabled = client.post(f"{BASE}/providers/{connection_id}/disable")

    assert listed.status_code == 200
    assert listed.json() == []
    assert verified.status_code == 404
    assert disabled.status_code == 404
    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        assert row is not None
        assert row.status == "not_verified"


def test_a_read_only_user_can_list_but_cannot_register_a_connection(secret) -> None:
    reader, reader_org = create_manager(permissions=("governance.providers.read",))
    try:
        with TestClient(_app_for(_actor(reader.id))) as client:
            client.headers.update({"X-Organization-ID": str(reader_org.id)})
            listed = client.get(f"{BASE}/providers")
            created = client.post(
                f"{BASE}/providers",
                json={"provider_kind": "email", "display_name": "Mail", "secret_ref": SECRET_NAME, "confirm": True},
            )
        assert listed.status_code == 200
        assert created.status_code == 403
    finally:
        _cleanup(reader_org.id)


def test_the_api_registers_verifies_and_disables_a_connection(tenant, secret, success_probe) -> None:
    organization_id, user_id = tenant
    with TestClient(_app_for(_actor(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        created = client.post(
            f"{BASE}/providers",
            json={"provider_kind": "email", "display_name": "Mail", "secret_ref": SECRET_NAME, "confirm": True},
        )
        assert created.status_code == 201
        connection_id = created.json()["id"]
        verified = client.post(f"{BASE}/providers/{connection_id}/verify")
        duplicate = client.post(
            f"{BASE}/providers",
            json={"provider_kind": "email", "display_name": "Again", "secret_ref": SECRET_NAME, "confirm": True},
        )
        disabled = client.post(f"{BASE}/providers/{connection_id}/disable")

    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert duplicate.status_code == 409
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert success_probe == [SECRET_VALUE]
