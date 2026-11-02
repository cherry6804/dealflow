"""Provider readiness for the execution policy (ADR-0032).

A provider is ready for an organization only when all of these hold:

1. a live (not disconnected) connection exists and its status is ``connected``;
2. the credential it references is still active;
3. the credential version is the one that passed verification (rotation or revocation through any
   route makes the connection not ready, without any extra write);
4. the last successful verification is within the freshness window.

Readiness is an input to ``app.governance.policy``. It never grants execution by itself, because the
other gates still apply. A connection can make a provider ready, but it cannot enable an AI capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.provider_secrets.service import STATUS_ACTIVE


class ReadinessCode(StrEnum):
    READY = "ready"
    NOT_CONNECTED = "not_connected"
    NOT_VERIFIED = "not_verified"
    VERIFYING = "verifying"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISCONNECTED = "disconnected"
    CREDENTIAL_REVOKED = "credential_revoked"
    CREDENTIAL_CHANGED = "credential_changed"
    STALE = "stale"


@dataclass(frozen=True)
class ConnectionReadiness:
    ready: bool
    code: ReadinessCode
    connection_id: UUID | None


_STATUS_CODES = {
    ProviderConnection.STATUS_UNVERIFIED: ReadinessCode.NOT_VERIFIED,
    ProviderConnection.STATUS_VERIFYING: ReadinessCode.VERIFYING,
    ProviderConnection.STATUS_DEGRADED: ReadinessCode.DEGRADED,
    ProviderConnection.STATUS_FAILED: ReadinessCode.FAILED,
    ProviderConnection.STATUS_DISCONNECTED: ReadinessCode.DISCONNECTED,
}


def readiness_for(
    connection: ProviderConnection,
    credential: ProviderCredential | None,
    *,
    now: datetime | None = None,
) -> ConnectionReadiness:
    """Decide readiness from loaded rows. Pure: it reads no state beyond its arguments."""
    current_time = now or datetime.now(UTC)
    if connection.status != ProviderConnection.STATUS_CONNECTED:
        code = _STATUS_CODES.get(connection.status, ReadinessCode.NOT_CONNECTED)
        return ConnectionReadiness(False, code, connection.id)
    if credential is None or credential.status != STATUS_ACTIVE:
        return ConnectionReadiness(False, ReadinessCode.CREDENTIAL_REVOKED, connection.id)
    if connection.verified_credential_version != credential.version:
        return ConnectionReadiness(False, ReadinessCode.CREDENTIAL_CHANGED, connection.id)
    freshness = timedelta(hours=get_settings().provider_connection_freshness_hours)
    if connection.last_verified_at is None or current_time - connection.last_verified_at > freshness:
        return ConnectionReadiness(False, ReadinessCode.STALE, connection.id)
    return ConnectionReadiness(True, ReadinessCode.READY, connection.id)


def connection_readiness(
    db: Session,
    *,
    organization_id: UUID,
    provider_key: str,
    now: datetime | None = None,
) -> ConnectionReadiness:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.organization_id == organization_id,
            ProviderConnection.provider_key == provider_key,
            ProviderConnection.status != ProviderConnection.STATUS_DISCONNECTED,
        )
    )
    if connection is None:
        return ConnectionReadiness(False, ReadinessCode.NOT_CONNECTED, None)
    credential = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.id == connection.credential_id,
            ProviderCredential.organization_id == organization_id,
        )
    )
    return readiness_for(connection, credential, now=now)


def any_provider_ready(
    db: Session,
    *,
    organization_id: UUID,
    provider_keys: tuple[str, ...],
    now: datetime | None = None,
) -> bool:
    """True when at least one of the providers is ready. An empty tuple is never ready."""
    return any(
        connection_readiness(db, organization_id=organization_id, provider_key=key, now=now).ready
        for key in provider_keys
    )
