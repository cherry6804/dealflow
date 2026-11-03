"""Provider registry and organization provider connections under /api/v1/ai (ADR-0032).

Reads need ``provider_credentials.read``. Every change needs ``provider_credentials.manage``, which
stays owner-only. Responses carry status and readiness. They never carry a credential, ciphertext
or a provider response. Verification is queued for the worker and is never run on the request path.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.authz.dependencies import permission_granted, require_permission
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.db.models.provider_verification_attempt import ProviderVerificationAttempt
from app.db.session import get_db_session
from app.provider_secrets.errors import ProviderSecretsConfigurationError
from app.provider_secrets.service import (
    CredentialConflictError,
    CredentialNotFoundError,
    InvalidCredentialInputError,
    ProviderCredentialError,
    UnsupportedProviderError,
)
from app.providers.readiness import readiness_for
from app.providers.registry import PROVIDERS
from app.providers.service import (
    ConnectionConflictError,
    ConnectionNotFoundError,
    ConnectionStateError,
    ProviderConnectionError,
    create_connection,
    credential_for_connection,
    disconnect_connection,
    get_connection,
    list_attempts,
    list_connections,
    request_verification,
    rotate_connection_secret,
)
from app.tenant.dependencies import TenantContext

provider_connection_routes = APIRouter(tags=["provider-connections"])


class ProviderDefinitionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    display_name: str
    category: str
    declared_operations: list[str]
    adapter_implemented: bool
    executable: bool


class ProviderListResponse(BaseModel):
    items: list[ProviderDefinitionResponse]


class ProviderConnectionCreateRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    secret: SecretStr


class ProviderConnectionRotateRequest(BaseModel):
    secret: SecretStr


class ProviderConnectionResponse(BaseModel):
    """Connection status and readiness. Contains no secret, ciphertext or provider response."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    provider_key: str
    label: str
    status: str
    status_reason_code: str | None
    ready: bool
    readiness_code: str
    credential_version: int | None
    verified_credential_version: int | None
    last_verified_at: datetime | None
    last_attempt_at: datetime | None
    consecutive_failures: int
    next_verification_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProviderConnectionListResponse(BaseModel):
    items: list[ProviderConnectionResponse]
    # Whether the caller may change connections. Lets the UI hide owner-only controls. The server still enforces it.
    can_manage: bool


class VerificationAttemptResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    attempted_at: datetime
    trigger: str
    outcome: str
    reason_code: str | None
    latency_ms: int
    credential_version: int
    adapter_version: str


class VerificationAttemptListResponse(BaseModel):
    items: list[VerificationAttemptResponse]


def _response(db: Session, connection: ProviderConnection) -> ProviderConnectionResponse:
    credential: ProviderCredential | None = credential_for_connection(db, connection)
    readiness = readiness_for(connection, credential)
    return ProviderConnectionResponse(
        id=connection.id,
        provider_key=connection.provider_key,
        label=connection.label,
        status=connection.status,
        status_reason_code=connection.status_reason_code,
        ready=readiness.ready,
        readiness_code=readiness.code.value,
        credential_version=credential.version if credential is not None else None,
        verified_credential_version=connection.verified_credential_version,
        last_verified_at=connection.last_verified_at,
        last_attempt_at=connection.last_attempt_at,
        consecutive_failures=connection.consecutive_failures,
        next_verification_at=connection.next_verification_at,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    """Map a failure to a response with a generic message. Never echoes input."""
    if isinstance(exc, (ConnectionNotFoundError, CredentialNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider connection was not found.")
    if isinstance(exc, (ConnectionConflictError, CredentialConflictError, ConnectionStateError)):
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
    if isinstance(exc, (ProviderConnectionError, ProviderCredentialError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The provider connection could not be changed.")
    raise exc


@provider_connection_routes.get("/providers", response_model=ProviderListResponse)
def list_providers(
    _tenant: TenantContext = Depends(require_permission("provider_credentials.read")),
) -> ProviderListResponse:
    """The provider registry. Declared operations are not executable until their gates pass."""
    return ProviderListResponse(
        items=[
            ProviderDefinitionResponse(
                key=provider.key,
                display_name=provider.display_name,
                category=provider.category.value,
                declared_operations=list(provider.declared_operations),
                adapter_implemented=provider.adapter_implemented,
                executable=provider.executable,
            )
            for provider in PROVIDERS
        ]
    )


@provider_connection_routes.get("/provider-connections", response_model=ProviderConnectionListResponse)
def list_provider_connections(
    tenant: TenantContext = Depends(require_permission("provider_credentials.read")),
    db: Session = Depends(get_db_session),
) -> ProviderConnectionListResponse:
    rows = list_connections(db, organization_id=tenant.organization_id)
    return ProviderConnectionListResponse(
        items=[_response(db, row) for row in rows],
        can_manage=permission_granted(db, tenant_context=tenant, permission_key="provider_credentials.manage"),
    )


@provider_connection_routes.get("/provider-connections/{connection_id}", response_model=ProviderConnectionResponse)
def get_provider_connection(
    connection_id: UUID,
    tenant: TenantContext = Depends(require_permission("provider_credentials.read")),
    db: Session = Depends(get_db_session),
) -> ProviderConnectionResponse:
    try:
        row = get_connection(db, organization_id=tenant.organization_id, connection_id=connection_id)
    except ProviderConnectionError as exc:
        raise _http_error(exc) from None
    return _response(db, row)


@provider_connection_routes.post(
    "/provider-connections",
    response_model=ProviderConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_provider_connection(
    payload: ProviderConnectionCreateRequest,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderConnectionResponse:
    """Store the credential and queue its first verification. The connection is not ready until verified."""
    try:
        row = create_connection(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            provider_key=payload.provider_key,
            label=payload.label,
            secret=payload.secret.get_secret_value(),
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderConnectionError, ProviderCredentialError, ProviderSecretsConfigurationError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return _response(db, row)


@provider_connection_routes.post(
    "/provider-connections/{connection_id}/verify",
    response_model=ProviderConnectionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def verify_provider_connection(
    connection_id: UUID,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderConnectionResponse:
    """Queue a verification for the worker. Returns ``verifying``. Never reports ``connected``."""
    try:
        row = request_verification(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            connection_id=connection_id,
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderConnectionError, ProviderCredentialError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return _response(db, row)


@provider_connection_routes.post(
    "/provider-connections/{connection_id}/rotate",
    response_model=ProviderConnectionResponse,
)
def rotate_provider_connection_secret(
    connection_id: UUID,
    payload: ProviderConnectionRotateRequest,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderConnectionResponse:
    try:
        row = rotate_connection_secret(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            connection_id=connection_id,
            secret=payload.secret.get_secret_value(),
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderConnectionError, ProviderCredentialError, ProviderSecretsConfigurationError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return _response(db, row)


@provider_connection_routes.post(
    "/provider-connections/{connection_id}/disconnect",
    response_model=ProviderConnectionResponse,
)
def disconnect_provider_connection(
    connection_id: UUID,
    tenant: TenantContext = Depends(require_permission("provider_credentials.manage")),
    db: Session = Depends(get_db_session),
) -> ProviderConnectionResponse:
    """Revoke the credential and end the connection. Its stored secret is destroyed."""
    try:
        row = disconnect_connection(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            connection_id=connection_id,
            correlation_id=str(uuid4()),
        )
        db.commit()
    except (ProviderConnectionError, ProviderCredentialError, ProviderSecretsConfigurationError) as exc:
        db.rollback()
        raise _http_error(exc) from None
    return _response(db, row)


@provider_connection_routes.get(
    "/provider-connections/{connection_id}/attempts",
    response_model=VerificationAttemptListResponse,
)
def list_verification_attempts(
    connection_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission("provider_credentials.read")),
    db: Session = Depends(get_db_session),
) -> VerificationAttemptListResponse:
    try:
        rows: list[ProviderVerificationAttempt] = list_attempts(
            db,
            organization_id=tenant.organization_id,
            connection_id=connection_id,
            limit=limit,
        )
    except ProviderConnectionError as exc:
        raise _http_error(exc) from None
    return VerificationAttemptListResponse(
        items=[
            VerificationAttemptResponse(
                id=row.id,
                attempted_at=row.attempted_at,
                trigger=row.trigger,
                outcome=row.outcome,
                reason_code=row.reason_code,
                latency_ms=row.latency_ms,
                credential_version=row.credential_version,
                adapter_version=row.adapter_version,
            )
            for row in rows
        ]
    )


# Canonical AI namespace only (ADR-0031 applies to the existing routes; these are new).
canonical_router = APIRouter(tags=["provider-connections"])
canonical_router.include_router(provider_connection_routes, prefix="/api/v1/ai")
