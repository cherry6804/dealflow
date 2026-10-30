"""Provider credential management for an organization (DFR1-011 subset for DFR1-015).

Responses return metadata only. The secret is accepted once on create and rotate, and is never
returned, logged or echoed in validation errors.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.models.provider_credential import ProviderCredential
from app.db.session import get_db_session
from app.provider_secrets.errors import ProviderSecretsConfigurationError
from app.provider_secrets.service import (
    CredentialConflictError,
    CredentialNotFoundError,
    InvalidCredentialInputError,
    ProviderCredentialError,
    UnsupportedProviderError,
    create_provider_credential,
    list_provider_credentials,
    revoke_provider_credential,
    rotate_provider_credential,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/provider-credentials", tags=["provider-credentials"])


class ProviderCredentialCreateRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    secret: SecretStr


class ProviderCredentialRotateRequest(BaseModel):
    secret: SecretStr


class ProviderCredentialResponse(BaseModel):
    """Credential metadata. Contains no secret, ciphertext or key material."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    provider_key: str
    label: str
    status: str
    version: int
    created_at: datetime
    rotated_at: datetime | None
    revoked_at: datetime | None


class ProviderCredentialListResponse(BaseModel):
    items: list[ProviderCredentialResponse]


def _http_error(exc: Exception) -> HTTPException:
    """Map a service failure to a response with a generic message."""
    if isinstance(exc, CredentialNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider credential was not found.")
    if isinstance(exc, CredentialConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, UnsupportedProviderError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, InvalidCredentialInputError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, ProviderSecretsConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential storage is not configured.",
        )
    raise exc


@router.get("", response_model=ProviderCredentialListResponse)
def list_credentials(
    tenant: TenantContext = Depends(require_permission("provider_credentials.read")),
    db: Session = Depends(get_db_session),
) -> ProviderCredentialListResponse:
    """List credential metadata for the selected organization."""
    rows = list_provider_credentials(db, organization_id=tenant.organization_id)
    return ProviderCredentialListResponse(
        items=[ProviderCredentialResponse.model_validate(row) for row in rows]
    )


@router.post("", response_model=ProviderCredentialResponse, status_code=status.HTTP_201_CREATED)
def create_credential(
    payload: ProviderCredentialCreateRequest,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderCredentialResponse:
    """Store a new active credential for one provider. Owner-only."""
    try:
        credential = create_provider_credential(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            provider_key=payload.provider_key,
            label=payload.label,
            secret=payload.secret.get_secret_value(),
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderCredentialError, ProviderSecretsConfigurationError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return ProviderCredentialResponse.model_validate(credential)


@router.post("/{credential_id}/rotate", response_model=ProviderCredentialResponse)
def rotate_credential(
    credential_id: UUID,
    payload: ProviderCredentialRotateRequest,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderCredentialResponse:
    """Replace the secret of an active credential. Owner-only."""
    try:
        credential = rotate_provider_credential(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            credential_id=credential_id,
            secret=payload.secret.get_secret_value(),
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderCredentialError, ProviderSecretsConfigurationError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return ProviderCredentialResponse.model_validate(credential)


@router.post("/{credential_id}/revoke", response_model=ProviderCredentialResponse)
def revoke_credential(
    credential_id: UUID,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderCredentialResponse:
    """Revoke a credential and destroy its stored ciphertext. Owner-only."""
    try:
        credential: ProviderCredential = revoke_provider_credential(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            credential_id=credential_id,
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderCredentialError, ProviderSecretsConfigurationError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return ProviderCredentialResponse.model_validate(credential)
