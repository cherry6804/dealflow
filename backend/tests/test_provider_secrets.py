"""Provider credential foundation: encryption, tenant isolation, lifecycle, audit and redaction.

Covers DFR1-011 (the narrow secrets boundary required by DFR1-015). The secret is accepted once
on create or rotate and is never returned, logged or persisted in plaintext.
"""

from __future__ import annotations

import base64
import json
import os
import pickle
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text

from app.api.provider_credentials import router as provider_credentials_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.provider_credential import ProviderCredential
from app.db.session import SessionLocal, get_db_session
from app.errors import register_error_handlers
from app.provider_secrets import service
from app.provider_secrets.cipher import (
    ALGORITHM,
    credential_associated_data,
    decrypt_secret,
    encrypt_secret,
)
from app.provider_secrets.errors import (
    ProviderSecretsConfigurationError,
    ProviderSecretsDecryptionError,
)
from app.provider_secrets.key_provider import build_key_provider
from app.provider_secrets.redaction import REDACTED, ProviderSecret
from tests.test_team_api import TestingSessionLocal, create_manager

BASE = "/api/v1/provider-credentials"
PROVIDER = "openai"


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def _secret() -> str:
    return f"sk-test-{uuid.uuid4().hex}"


@pytest.fixture
def keyring(monkeypatch) -> Iterator[None]:
    """Configure a local test keyring with two keys, the newer one active."""
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "test-v2")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"test-v1": _key(), "test-v2": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def cleanup() -> Iterator[list]:
    created: list = []
    yield created
    with SessionLocal() as db:
        for organization_id in created:
            db.execute(delete(ProviderCredential).where(ProviderCredential.organization_id == organization_id))
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


def _create(db, *, organization_id, user_id, secret: str | None = None) -> ProviderCredential:
    credential = service.create_provider_credential(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        provider_key=PROVIDER,
        label="Primary",
        secret=secret or _secret(),
    )
    db.commit()
    return credential


# --- encryption primitives -------------------------------------------------------------------


def test_round_trip_uses_authenticated_encryption_and_key_metadata(keyring) -> None:
    keys = build_key_provider()
    aad = credential_associated_data(
        organization_id=uuid.uuid4(), provider_key=PROVIDER, credential_id=uuid.uuid4(), version=1
    )
    secret = _secret()

    encrypted = encrypt_secret(secret, associated_data=aad, keys=keys)

    assert encrypted.algorithm == ALGORITHM
    assert encrypted.key_id == "test-v2"
    assert secret not in encrypted.ciphertext
    assert decrypt_secret(
        encrypted.ciphertext, key_id=encrypted.key_id, algorithm=encrypted.algorithm,
        associated_data=aad, keys=keys,
    ) == secret


def test_invalid_ciphertext_is_rejected_with_a_generic_error(keyring) -> None:
    keys = build_key_provider()
    aad = b"aad"
    encrypted = encrypt_secret(_secret(), associated_data=aad, keys=keys)
    tampered = base64.b64encode(bytearray(base64.b64decode(encrypted.ciphertext))[:-1] + b"\x00").decode()

    with pytest.raises(ProviderSecretsDecryptionError, match="could not be decrypted") as tampered_error:
        decrypt_secret(tampered, key_id="test-v2", algorithm=ALGORITHM, associated_data=aad, keys=keys)
    assert encrypted.ciphertext not in str(tampered_error.value)

    for bad in ("not base64!!", base64.b64encode(b"short").decode()):
        with pytest.raises(ProviderSecretsDecryptionError):
            decrypt_secret(bad, key_id="test-v2", algorithm=ALGORITHM, associated_data=aad, keys=keys)

    with pytest.raises(ProviderSecretsDecryptionError, match="unsupported algorithm"):
        decrypt_secret(
            encrypted.ciphertext, key_id="test-v2", algorithm="none", associated_data=aad, keys=keys,
        )


def test_ciphertext_is_bound_to_its_associated_data(keyring) -> None:
    keys = build_key_provider()
    org = uuid.uuid4()
    original = credential_associated_data(organization_id=org, provider_key=PROVIDER, credential_id=uuid.uuid4(), version=1)
    other_row = credential_associated_data(organization_id=org, provider_key=PROVIDER, credential_id=uuid.uuid4(), version=1)
    newer_version = credential_associated_data(organization_id=org, provider_key=PROVIDER, credential_id=uuid.uuid4(), version=2)
    encrypted = encrypt_secret(_secret(), associated_data=original, keys=keys)

    credential_id = uuid.uuid4()
    same_row = credential_associated_data(
        organization_id=org, provider_key=PROVIDER, credential_id=credential_id, version=1
    )
    other_org_same_row = credential_associated_data(
        organization_id=uuid.uuid4(), provider_key=PROVIDER, credential_id=credential_id, version=1
    )
    other_provider_same_row = credential_associated_data(
        organization_id=org, provider_key="other-provider", credential_id=credential_id, version=1
    )
    encrypted_for_row = encrypt_secret(_secret(), associated_data=same_row, keys=keys)
    assert decrypt_secret(
        encrypted_for_row.ciphertext, key_id=encrypted_for_row.key_id, algorithm=encrypted_for_row.algorithm,
        associated_data=same_row, keys=keys,
    )

    for wrong in (other_org_same_row, other_provider_same_row):
        with pytest.raises(ProviderSecretsDecryptionError):
            decrypt_secret(
                encrypted_for_row.ciphertext, key_id=encrypted_for_row.key_id,
                algorithm=encrypted_for_row.algorithm, associated_data=wrong, keys=keys,
            )

    for wrong in (other_row, newer_version):
        with pytest.raises(ProviderSecretsDecryptionError):
            decrypt_secret(
                encrypted.ciphertext, key_id=encrypted.key_id, algorithm=encrypted.algorithm,
                associated_data=wrong, keys=keys,
            )


def test_unknown_key_id_fails_closed(keyring) -> None:
    keys = build_key_provider()
    encrypted = encrypt_secret(_secret(), associated_data=b"aad", keys=keys)

    with pytest.raises(ProviderSecretsConfigurationError, match="unavailable"):
        decrypt_secret(
            encrypted.ciphertext, key_id="retired-key", algorithm=ALGORITHM, associated_data=b"aad", keys=keys,
        )


# --- key sources and production safety --------------------------------------------------------


def test_missing_keyring_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("PROVIDER_SECRETS_KEYRING", raising=False)
    monkeypatch.delenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ProviderSecretsConfigurationError, match="not configured"):
            build_key_provider()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_missing_production_key_fails_closed(monkeypatch) -> None:
    production = SimpleNamespace(
        app_environment="production",
        provider_secrets_key_provider="local_keyring",
        provider_secrets_keyring=None,
        provider_secrets_active_key_id=None,
    )
    monkeypatch.setattr("app.provider_secrets.key_provider.get_settings", lambda: production)

    with pytest.raises(ProviderSecretsConfigurationError, match="managed key provider"):
        build_key_provider()


def test_local_keyring_is_refused_in_production_even_when_configured(monkeypatch) -> None:
    configured = SimpleNamespace(
        app_environment="production",
        provider_secrets_key_provider="local_keyring",
        provider_secrets_keyring=SimpleNamespace(get_secret_value=lambda: json.dumps({"k": _key()})),
        provider_secrets_active_key_id="k",
    )
    monkeypatch.setattr("app.provider_secrets.key_provider.get_settings", lambda: configured)

    with pytest.raises(ProviderSecretsConfigurationError):
        build_key_provider()


def test_managed_kms_boundary_fails_closed_and_is_not_claimed_as_implemented(monkeypatch) -> None:
    managed = SimpleNamespace(
        app_environment="development",
        provider_secrets_key_provider="managed_kms",
        provider_secrets_keyring=None,
        provider_secrets_active_key_id=None,
    )
    monkeypatch.setattr("app.provider_secrets.key_provider.get_settings", lambda: managed)

    with pytest.raises(ProviderSecretsConfigurationError, match="not implemented"):
        build_key_provider().active_key_id()
    with pytest.raises(ProviderSecretsConfigurationError, match="not implemented"):
        build_key_provider().key_for("any")


@pytest.mark.parametrize(
    "keyring_value",
    [
        "not json",
        json.dumps([]),
        json.dumps({"k": 123}),
        json.dumps({"k": base64.urlsafe_b64encode(b"too-short").decode()}),
    ],
)
def test_malformed_keyring_fails_closed(monkeypatch, keyring_value: str) -> None:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "k")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", keyring_value)
    get_settings.cache_clear()
    try:
        with pytest.raises(ProviderSecretsConfigurationError):
            build_key_provider()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_create_without_key_writes_nothing(monkeypatch, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    def no_keyring():
        raise ProviderSecretsConfigurationError("Provider secrets keyring is not configured.")

    monkeypatch.setattr("app.provider_secrets.service.build_key_provider", no_keyring)

    with SessionLocal() as db:
        with pytest.raises(ProviderSecretsConfigurationError):
            service.create_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id,
                provider_key=PROVIDER, label="Primary", secret=_secret(),
            )
        db.rollback()
        count = db.scalar(
            select(func.count()).select_from(ProviderCredential).where(
                ProviderCredential.organization_id == organization.id
            )
        )
    assert count == 0


# --- lifecycle, plaintext and isolation -------------------------------------------------------


def test_create_stores_ciphertext_and_backend_retrieval_returns_the_secret(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    secret = _secret()

    with SessionLocal() as db:
        credential = _create(db, organization_id=organization.id, user_id=user.id, secret=secret)
        retrieved = service.get_provider_secret_for_gateway(
            db, organization_id=organization.id, provider_key=PROVIDER
        )

    assert credential.status == "active"
    assert credential.version == 1
    assert credential.ciphertext and secret not in credential.ciphertext
    assert credential.encryption_key_id == "test-v2"
    assert retrieved.reveal() == secret


def test_plaintext_is_never_persisted_in_any_column_or_audit_record(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    secret = _secret()

    with SessionLocal() as db:
        credential = _create(db, organization_id=organization.id, user_id=user.id, secret=secret)
        service.rotate_provider_credential(
            db, organization_id=organization.id, actor_user_id=user.id,
            credential_id=credential.id, secret=_secret(),
        )
        db.commit()
        row = db.execute(text("SELECT * FROM provider_credentials WHERE id = :id"), {"id": credential.id}).mappings().one()
        audits = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization.id)).all()

    stored_text = " ".join(str(value) for value in row.values())
    audit_text = " ".join(f"{event.resource_id} {event.event_metadata} {event.action}" for event in audits)
    assert secret not in stored_text
    assert secret not in audit_text


def test_rotation_replaces_the_secret_and_increments_the_version(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    old_secret, new_secret = _secret(), _secret()

    with SessionLocal() as db:
        credential = _create(db, organization_id=organization.id, user_id=user.id, secret=old_secret)
        old_ciphertext = credential.ciphertext
        service.rotate_provider_credential(
            db, organization_id=organization.id, actor_user_id=user.id,
            credential_id=credential.id, secret=new_secret,
        )
        db.commit()
        refreshed = service.get_provider_secret_for_gateway(db, organization_id=organization.id, provider_key=PROVIDER)
        version = db.get(ProviderCredential, credential.id).version

    assert version == 2
    assert refreshed.reveal() == new_secret
    assert refreshed.reveal() != old_secret
    assert old_ciphertext != credential.ciphertext


def test_revocation_destroys_ciphertext_and_blocks_retrieval(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)

    with SessionLocal() as db:
        credential = _create(db, organization_id=organization.id, user_id=user.id)
        service.revoke_provider_credential(
            db, organization_id=organization.id, actor_user_id=user.id, credential_id=credential.id,
        )
        db.commit()
        revoked = db.get(ProviderCredential, credential.id)

        assert revoked.status == "revoked"
        assert revoked.ciphertext is None
        assert revoked.encryption_key_id is None
        with pytest.raises(service.NoActiveCredentialError):
            service.get_provider_secret_for_gateway(db, organization_id=organization.id, provider_key=PROVIDER)
        with pytest.raises(service.CredentialConflictError):
            service.rotate_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id,
                credential_id=credential.id, secret=_secret(),
            )
        with pytest.raises(service.CredentialConflictError):
            service.revoke_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id, credential_id=credential.id,
            )


def test_only_one_active_credential_per_provider(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)

    with SessionLocal() as db:
        _create(db, organization_id=organization.id, user_id=user.id)
        with pytest.raises(service.CredentialConflictError, match="Rotate"):
            service.create_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id,
                provider_key=PROVIDER, label="Second", secret=_secret(),
            )


def test_cross_organization_access_is_denied(keyring, cleanup) -> None:
    owner, org_a = create_manager(permissions=("provider_credentials.manage",))
    _, org_b = create_manager(permissions=("provider_credentials.manage",))
    cleanup.extend([org_a.id, org_b.id])

    with SessionLocal() as db:
        credential = _create(db, organization_id=org_a.id, user_id=owner.id)

        with pytest.raises(service.CredentialNotFoundError):
            service.rotate_provider_credential(
                db, organization_id=org_b.id, actor_user_id=owner.id,
                credential_id=credential.id, secret=_secret(),
            )
        with pytest.raises(service.CredentialNotFoundError):
            service.revoke_provider_credential(
                db, organization_id=org_b.id, actor_user_id=owner.id, credential_id=credential.id,
            )
        with pytest.raises(service.NoActiveCredentialError):
            service.get_provider_secret_for_gateway(db, organization_id=org_b.id, provider_key=PROVIDER)
        assert service.list_provider_credentials(db, organization_id=org_b.id) == []


def test_unsupported_provider_and_invalid_secret_are_refused(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    leaked = "has space sk-leak"

    with SessionLocal() as db:
        with pytest.raises(service.UnsupportedProviderError):
            service.create_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id,
                provider_key="anthropic", label="x", secret=_secret(),
            )
        with pytest.raises(service.InvalidCredentialInputError) as invalid:
            service.create_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id,
                provider_key=PROVIDER, label="x", secret=leaked,
            )
        with pytest.raises(service.InvalidCredentialInputError):
            service.create_provider_credential(
                db, organization_id=organization.id, actor_user_id=user.id,
                provider_key=PROVIDER, label="x", secret="a" * 513,
            )
        db.rollback()

    assert "sk-leak" not in str(invalid.value)


def test_audit_records_create_rotate_and_revoke_without_the_secret(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    secret = _secret()

    with SessionLocal() as db:
        credential = _create(db, organization_id=organization.id, user_id=user.id, secret=secret)
        service.rotate_provider_credential(
            db, organization_id=organization.id, actor_user_id=user.id, credential_id=credential.id, secret=_secret(),
        )
        service.revoke_provider_credential(
            db, organization_id=organization.id, actor_user_id=user.id, credential_id=credential.id,
        )
        db.commit()
        credential_id = str(credential.id)
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization.id,
                AuditEvent.event_type == service.PROVIDER_CREDENTIAL_EVENT_TYPE,
            )
        ).all()

    assert sorted(event.action for event in events) == sorted(
        [service.ACTION_CREATED, service.ACTION_ROTATED, service.ACTION_REVOKED]
    )
    for event in events:
        assert event.user_id == user.id
        assert event.resource_id == credential_id
        assert secret not in (event.event_metadata or "")


def test_only_the_owner_template_grants_provider_credential_management() -> None:
    from app.team.service import DEFAULT_ROLE_TEMPLATES

    assert "provider_credentials.manage" in DEFAULT_ROLE_TEMPLATES["DealFlow Owner"]
    for role_name, keys in DEFAULT_ROLE_TEMPLATES.items():
        if role_name == "DealFlow Owner":
            continue
        assert "provider_credentials.manage" not in keys, role_name
        assert "provider_credentials.read" not in keys or role_name == "Admin", role_name


# --- redaction --------------------------------------------------------------------------------


def test_provider_secret_is_redacted_in_representation_and_serialization() -> None:
    value = _secret()
    wrapped = ProviderSecret(value)

    assert value not in repr(wrapped)
    assert value not in str(wrapped)
    assert REDACTED in repr(wrapped)
    assert wrapped.reveal() == value
    with pytest.raises(TypeError):
        pickle.dumps(wrapped)


def test_decryption_errors_do_not_expose_ciphertext(keyring) -> None:
    keys = build_key_provider()
    encrypted = encrypt_secret(_secret(), associated_data=b"aad", keys=keys)
    with pytest.raises(ProviderSecretsDecryptionError) as failure:
        decrypt_secret(encrypted.ciphertext, key_id="test-v2", algorithm=ALGORITHM, associated_data=b"other", keys=keys)

    assert encrypted.ciphertext not in str(failure.value)
    assert failure.value.__suppress_context__ is True


# --- API ------------------------------------------------------------------------------------


def _app_for(user) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(provider_credentials_router)

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


def test_api_create_returns_metadata_and_never_the_secret(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    cleanup.append(organization.id)
    secret = _secret()

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        created = client.post(BASE, json={"provider_key": PROVIDER, "label": "Primary", "secret": secret})
        listed = client.get(BASE)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "active"
    assert body["version"] == 1
    assert secret not in created.text and secret not in listed.text
    assert not {"secret", "ciphertext", "encryption_key_id"} & set(body)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]


def test_api_requires_the_manage_permission_to_change_credentials(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.post(BASE, json={"provider_key": PROVIDER, "label": "x", "secret": _secret()})

    assert response.status_code == 403


def test_api_listing_requires_the_read_permission(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("deals.read",))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(BASE)

    assert response.status_code == 403


def test_api_validation_error_does_not_echo_the_secret(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    marker = f"sk-marker-{uuid.uuid4().hex}"

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.post(BASE, json={"provider_key": PROVIDER, "label": "x", "secret": {"value": marker}})

    assert response.status_code == 422
    assert marker not in response.text
    assert REDACTED in response.text


def test_api_cross_organization_rotate_and_revoke_return_not_found(keyring, cleanup) -> None:
    owner, org_a = create_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    other, org_b = create_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    cleanup.extend([org_a.id, org_b.id])

    with TestClient(_app_for(owner)) as client:
        client.headers.update({"X-Organization-ID": str(org_a.id)})
        credential_id = client.post(BASE, json={"provider_key": PROVIDER, "label": "x", "secret": _secret()}).json()["id"]

    with TestClient(_app_for(other)) as client:
        client.headers.update({"X-Organization-ID": str(org_b.id)})
        rotated = client.post(f"{BASE}/{credential_id}/rotate", json={"secret": _secret()})
        revoked = client.post(f"{BASE}/{credential_id}/revoke")

    assert rotated.status_code == 404
    assert revoked.status_code == 404


def test_api_fails_closed_without_key_configuration(monkeypatch, cleanup) -> None:
    monkeypatch.delenv("PROVIDER_SECRETS_KEYRING", raising=False)
    monkeypatch.delenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", raising=False)
    get_settings.cache_clear()
    user, organization = create_manager(permissions=("provider_credentials.manage",))
    cleanup.append(organization.id)
    try:
        with TestClient(_app_for(user)) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.post(BASE, json={"provider_key": PROVIDER, "label": "x", "secret": _secret()})
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

    assert response.status_code == 503
    assert "Provider credential storage is not configured." in response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ProviderCredential).where(
            ProviderCredential.organization_id == organization.id
        )) == 0


def test_api_revoke_clears_the_secret_and_reports_status(keyring, cleanup) -> None:
    user, organization = create_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    cleanup.append(organization.id)

    with TestClient(_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        credential_id = client.post(BASE, json={"provider_key": PROVIDER, "label": "x", "secret": _secret()}).json()["id"]
        revoked = client.post(f"{BASE}/{credential_id}/revoke")
        again = client.post(f"{BASE}/{credential_id}/revoke")

    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
    assert again.status_code == 409
