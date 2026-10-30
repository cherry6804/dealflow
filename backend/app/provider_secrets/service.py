"""Provider credential lifecycle: create, rotate, revoke and backend-only retrieval.

Authorization is enforced by the API layer (organization membership and permissions). This
module scopes every query by organization, so a credential identifier from another organization
is reported as not found. Audit events record metadata only, never the secret.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent
from app.db.models.provider_credential import ProviderCredential
from app.provider_secrets.cipher import (
    credential_associated_data,
    decrypt_secret,
    encrypt_secret,
)
from app.provider_secrets.errors import ProviderSecretsDecryptionError
from app.provider_secrets.key_provider import build_key_provider
from app.provider_secrets.redaction import ProviderSecret

# Only providers with a working adapter are accepted. Others are not claimed as supported.
SUPPORTED_PROVIDER_KEYS = frozenset({"openai"})

MAX_SECRET_LENGTH = 512
MAX_LABEL_LENGTH = 120

STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"

PROVIDER_CREDENTIAL_EVENT_TYPE = "provider_credentials"
ACTION_CREATED = "provider_credential.created"
ACTION_ROTATED = "provider_credential.rotated"
ACTION_REVOKED = "provider_credential.revoked"
PERMISSION_MANAGE = "provider_credentials.manage"


class ProviderCredentialError(Exception):
    """Base class for provider credential failures. Messages never include secret values."""


class UnsupportedProviderError(ProviderCredentialError):
    """The requested provider has no supported adapter."""


class InvalidCredentialInputError(ProviderCredentialError):
    """The secret or label does not meet the input rules."""


class CredentialNotFoundError(ProviderCredentialError):
    """No credential with this identifier exists in the selected organization."""


class CredentialConflictError(ProviderCredentialError):
    """The requested change conflicts with the credential's current state."""


class NoActiveCredentialError(ProviderCredentialError):
    """No active credential exists for the requested provider."""


def _require_supported_provider(provider_key: str) -> None:
    if provider_key not in SUPPORTED_PROVIDER_KEYS:
        raise UnsupportedProviderError("This provider is not supported.")


def _validate_secret(secret: str) -> str:
    value = secret.strip()
    if not value or len(value) > MAX_SECRET_LENGTH or any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise InvalidCredentialInputError(
            "Secret must be a single non-empty value of at most 512 characters without whitespace."
        )
    return value


def _validate_label(label: str) -> str:
    value = label.strip()
    if not value or len(value) > MAX_LABEL_LENGTH:
        raise InvalidCredentialInputError("Label must be between 1 and 120 characters.")
    return value


def _associated_data(credential: ProviderCredential) -> bytes:
    return credential_associated_data(
        organization_id=credential.organization_id,
        provider_key=credential.provider_key,
        credential_id=credential.id,
        version=credential.version,
    )


def _seal(credential: ProviderCredential, secret: str) -> None:
    """Encrypt before any database write, so a configuration failure writes nothing."""
    encrypted = encrypt_secret(
        secret,
        associated_data=_associated_data(credential),
        keys=build_key_provider(),
    )
    credential.ciphertext = encrypted.ciphertext
    credential.encryption_key_id = encrypted.key_id
    credential.encryption_algorithm = encrypted.algorithm


def _get_in_organization(db: Session, *, organization_id: UUID, credential_id: UUID) -> ProviderCredential:
    """Load a credential for update, so concurrent rotate and revoke requests serialize."""
    credential = db.scalar(
        select(ProviderCredential)
        .where(
            ProviderCredential.id == credential_id,
            ProviderCredential.organization_id == organization_id,
        )
        .with_for_update()
    )
    if credential is None:
        raise CredentialNotFoundError("Provider credential was not found.")
    return credential


def _audit(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    action: str,
    credential: ProviderCredential,
    correlation_id: str | None,
) -> None:
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=PROVIDER_CREDENTIAL_EVENT_TYPE,
            action=action,
            decision="allowed",
            permission_key=PERMISSION_MANAGE,
            resource_type="provider_credential",
            resource_id=str(credential.id),
            correlation_id=correlation_id or str(uuid4()),
            event_metadata=json.dumps(
                {
                    "provider_key": credential.provider_key,
                    "version": credential.version,
                    "status": credential.status,
                    "encryption_key_id": credential.encryption_key_id,
                },
                separators=(",", ":"),
            ),
        )
    )


def list_provider_credentials(db: Session, *, organization_id: UUID) -> list[ProviderCredential]:
    """Return credential metadata for one organization. Ciphertext is not exposed by callers."""
    return list(
        db.scalars(
            select(ProviderCredential)
            .where(ProviderCredential.organization_id == organization_id)
            .order_by(ProviderCredential.created_at, ProviderCredential.id)
        )
    )


def create_provider_credential(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    provider_key: str,
    label: str,
    secret: str,
    correlation_id: str | None = None,
) -> ProviderCredential:
    """Store a new active credential. Rotate an existing one instead of creating a second."""
    _require_supported_provider(provider_key)
    value = _validate_secret(secret)
    label_value = _validate_label(label)

    existing = db.scalar(
        select(ProviderCredential.id).where(
            ProviderCredential.organization_id == organization_id,
            ProviderCredential.provider_key == provider_key,
            ProviderCredential.status == STATUS_ACTIVE,
        )
    )
    if existing is not None:
        raise CredentialConflictError("An active credential already exists for this provider. Rotate it instead.")

    credential = ProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        provider_key=provider_key,
        label=label_value,
        status=STATUS_ACTIVE,
        version=1,
        created_by_user_id=actor_user_id,
    )
    _seal(credential, value)
    db.add(credential)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent create won the partial unique index for this provider.
        db.rollback()
        raise CredentialConflictError("An active credential already exists for this provider. Rotate it instead.") from None
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=ACTION_CREATED,
        credential=credential,
        correlation_id=correlation_id,
    )
    return credential


def rotate_provider_credential(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    credential_id: UUID,
    secret: str,
    correlation_id: str | None = None,
) -> ProviderCredential:
    """Replace the secret. The previous ciphertext is overwritten and not kept."""
    credential = _get_in_organization(db, organization_id=organization_id, credential_id=credential_id)
    if credential.status != STATUS_ACTIVE:
        raise CredentialConflictError("A revoked credential cannot be rotated. Create a new credential.")
    value = _validate_secret(secret)

    credential.version += 1
    _seal(credential, value)
    credential.rotated_by_user_id = actor_user_id
    credential.rotated_at = datetime.now(UTC)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=ACTION_ROTATED,
        credential=credential,
        correlation_id=correlation_id,
    )
    return credential


def revoke_provider_credential(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    credential_id: UUID,
    correlation_id: str | None = None,
) -> ProviderCredential:
    """Revoke the credential and clear its ciphertext and key metadata."""
    credential = _get_in_organization(db, organization_id=organization_id, credential_id=credential_id)
    if credential.status != STATUS_ACTIVE:
        raise CredentialConflictError("Provider credential is already revoked.")

    credential.status = STATUS_REVOKED
    credential.ciphertext = None
    credential.encryption_key_id = None
    credential.encryption_algorithm = None
    credential.revoked_by_user_id = actor_user_id
    credential.revoked_at = datetime.now(UTC)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=ACTION_REVOKED,
        credential=credential,
        correlation_id=correlation_id,
    )
    return credential


def get_provider_secret_for_gateway(
    db: Session,
    *,
    organization_id: UUID,
    provider_key: str,
) -> ProviderSecret:
    """Backend-only: resolve the active secret for one provider call.

    No API route uses this function. It fails closed when no active credential exists, when the
    key is unavailable, or when the ciphertext does not authenticate.
    """
    _require_supported_provider(provider_key)
    credential = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == organization_id,
            ProviderCredential.provider_key == provider_key,
            ProviderCredential.status == STATUS_ACTIVE,
        )
    )
    if credential is None or credential.ciphertext is None or credential.encryption_key_id is None:
        raise NoActiveCredentialError("No active provider credential is configured.")

    plaintext = decrypt_secret(
        credential.ciphertext,
        key_id=credential.encryption_key_id,
        algorithm=credential.encryption_algorithm or "",
        associated_data=_associated_data(credential),
        keys=build_key_provider(),
    )
    return ProviderSecret(plaintext)


__all__ = [
    "SUPPORTED_PROVIDER_KEYS",
    "CredentialConflictError",
    "CredentialNotFoundError",
    "InvalidCredentialInputError",
    "NoActiveCredentialError",
    "ProviderCredentialError",
    "ProviderSecretsDecryptionError",
    "UnsupportedProviderError",
    "create_provider_credential",
    "get_provider_secret_for_gateway",
    "list_provider_credentials",
    "revoke_provider_credential",
    "rotate_provider_credential",
]
