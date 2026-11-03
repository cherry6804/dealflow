"""Provider connection lifecycle (ADR-0032).

Every state change happens under a row lock on the connection, in the caller's transaction. Each
verification is queued as an outbox event and runs in the WS3 worker, never on the request path.

Status changes are never made by request handlers except to queue a check (``verifying``) or to
disconnect. ``connected`` is written only by the verification handler, after an adapter reports a
successful check for the current credential version.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.db.models.provider_verification_attempt import ProviderVerificationAttempt
from app.outbox.service import enqueue_event
from app.provider_secrets.service import (
    STATUS_ACTIVE,
    UnsupportedProviderError,
    create_provider_credential,
    revoke_provider_credential,
    rotate_provider_credential,
)
from app.providers.base import VerificationOutcome
from app.providers.registry import get_provider

PROVIDER_VERIFICATION_EVENT = "provider.verification_requested"
PROVIDER_CONNECTION_AUDIT_EVENT = "provider_connection"
PERMISSION_MANAGE = "provider_credentials.manage"
BASE_BACKOFF_SECONDS = 300

TRIGGER_CREATED = "created"
TRIGGER_ROTATED = "rotated"
TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"

REASON_VERIFICATION_REQUESTED = "verification_requested"
REASON_ROTATED = "rotated_pending_verification"
REASON_DISCONNECTED = "disconnected_by_operator"
REASON_CREDENTIAL_REVOKED = "credential_revoked"
REASON_FAILED_REPEATEDLY = "verification_failed_repeatedly"
REASON_ADAPTER_NOT_IMPLEMENTED = "adapter_not_implemented"


class ProviderConnectionError(Exception):
    """Base class for connection failures that callers can report."""


class ConnectionNotFoundError(ProviderConnectionError):
    """No connection with this identifier exists in the organization."""


class ConnectionConflictError(ProviderConnectionError):
    """The operation conflicts with the connection's current state."""


class ConnectionStateError(ProviderConnectionError):
    """The connection cannot be changed in its current state."""


def _get_locked(db: Session, *, organization_id: UUID, connection_id: UUID) -> ProviderConnection:
    connection = db.scalar(
        select(ProviderConnection)
        .where(
            ProviderConnection.id == connection_id,
            ProviderConnection.organization_id == organization_id,
        )
        .with_for_update()
    )
    if connection is None:
        raise ConnectionNotFoundError("Provider connection was not found.")
    return connection


def _credential_for(db: Session, connection: ProviderConnection) -> ProviderCredential | None:
    return db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.id == connection.credential_id,
            ProviderCredential.organization_id == connection.organization_id,
        )
    )


def _audit(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    connection: ProviderConnection,
    correlation_id: str | None,
    extra: dict[str, object] | None = None,
    requested: AuditEvent | None = None,
) -> None:
    metadata: dict[str, object] = {
        "provider_key": connection.provider_key,
        "status": connection.status,
        "reason_code": connection.status_reason_code,
        "credential_version": connection.verified_credential_version,
    }
    if extra:
        metadata.update(extra)
    # Admin operations pass the requested row (WP3). Worker outcomes pass none and keep no lifecycle.
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=PROVIDER_CONNECTION_AUDIT_EVENT,
            action=action,
            decision="allowed",
            outcome=OUTCOME_COMPLETED if requested is not None else None,
            causation_id=str(requested.id) if requested is not None else None,
            permission_key=PERMISSION_MANAGE,
            resource_type="provider_connection",
            resource_id=str(connection.id),
            correlation_id=requested.correlation_id if requested is not None else (correlation_id or str(uuid4())),
            event_metadata=json.dumps(metadata, separators=(",", ":"), default=str),
        )
    )


def _requested(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    action: str,
    connection_id: UUID,
    provider_key: str,
    correlation_id: str | None,
) -> AuditEvent:
    """Commit the attempt before the connection changes (WP3). Holds no credential material."""
    return persist_independent_audit_event(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=PROVIDER_CONNECTION_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key=PERMISSION_MANAGE,
        resource_type="provider_connection",
        resource_id=str(connection_id),
        correlation_id=correlation_id,
        metadata={"provider_key": provider_key},
    )


def _set_verifying(connection: ProviderConnection, *, reason: str) -> None:
    connection.status = ProviderConnection.STATUS_VERIFYING
    connection.status_reason_code = reason
    connection.next_verification_at = None
    connection.version += 1


def _enqueue_verification(
    db: Session,
    *,
    connection: ProviderConnection,
    credential_version: int,
    trigger: str,
    idempotency_key: str,
    correlation_id: str | None,
) -> None:
    enqueue_event(
        db,
        organization_id=connection.organization_id,
        event_type=PROVIDER_VERIFICATION_EVENT,
        aggregate_type="provider_connection",
        aggregate_id=str(connection.id),
        idempotency_key=idempotency_key,
        payload={
            "connection_id": str(connection.id),
            "credential_version": credential_version,
            "trigger": trigger,
        },
        correlation_id=correlation_id,
    )


def list_connections(db: Session, *, organization_id: UUID) -> list[ProviderConnection]:
    return list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.organization_id == organization_id)
            .order_by(ProviderConnection.created_at, ProviderConnection.id)
        )
    )


def get_connection(db: Session, *, organization_id: UUID, connection_id: UUID) -> ProviderConnection:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == connection_id,
            ProviderConnection.organization_id == organization_id,
        )
    )
    if connection is None:
        raise ConnectionNotFoundError("Provider connection was not found.")
    return connection


def credential_for_connection(db: Session, connection: ProviderConnection) -> ProviderCredential | None:
    return _credential_for(db, connection)


def create_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    provider_key: str,
    label: str,
    secret: str,
    correlation_id: str | None = None,
) -> ProviderConnection:
    """Store the credential, create the connection, and queue its first verification.

    The connection is ``verifying`` when this returns. It is not usable until the worker verifies it.
    """
    if get_provider(provider_key) is None:
        raise UnsupportedProviderError("This provider is not supported.")
    existing = db.scalar(
        select(ProviderConnection.id).where(
            ProviderConnection.organization_id == organization_id,
            ProviderConnection.provider_key == provider_key,
            ProviderConnection.status != ProviderConnection.STATUS_DISCONNECTED,
        )
    )
    if existing is not None:
        raise ConnectionConflictError(
            "A connection already exists for this provider. Rotate its secret or disconnect it first."
        )

    connection_id = uuid4()
    requested = _requested(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="created",
        connection_id=connection_id,
        provider_key=provider_key,
        correlation_id=correlation_id,
    )
    credential = create_provider_credential(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        provider_key=provider_key,
        label=label,
        secret=secret,
        correlation_id=correlation_id,
    )
    connection = ProviderConnection(
        id=connection_id,
        organization_id=organization_id,
        provider_key=provider_key,
        credential_id=credential.id,
        label=label,
        status=ProviderConnection.STATUS_UNVERIFIED,
        consecutive_failures=0,
        version=1,
        created_by_user_id=actor_user_id,
    )
    db.add(connection)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConnectionConflictError(
            "A connection already exists for this provider. Rotate its secret or disconnect it first."
        ) from None

    _set_verifying(connection, reason=REASON_VERIFICATION_REQUESTED)
    _enqueue_verification(
        db,
        connection=connection,
        credential_version=credential.version,
        trigger=TRIGGER_CREATED,
        idempotency_key=f"provider-verify:{connection.id}:{uuid.uuid4()}",
        correlation_id=correlation_id,
    )
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="created",
        connection=connection,
        correlation_id=correlation_id,
        requested=requested,
    )
    db.flush()
    return connection


def request_verification(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    connection_id: UUID,
    correlation_id: str | None = None,
) -> ProviderConnection:
    connection = _get_locked(db, organization_id=organization_id, connection_id=connection_id)
    if connection.status == ProviderConnection.STATUS_DISCONNECTED:
        raise ConnectionStateError("This connection is disconnected. Create a new connection to verify again.")
    credential = _credential_for(db, connection)
    if credential is None or credential.status != STATUS_ACTIVE:
        raise ConnectionStateError("The credential for this connection is revoked. Create a new connection.")

    requested = _requested(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="verification_requested",
        connection_id=connection.id,
        provider_key=connection.provider_key,
        correlation_id=correlation_id,
    )
    _set_verifying(connection, reason=REASON_VERIFICATION_REQUESTED)
    _enqueue_verification(
        db,
        connection=connection,
        credential_version=credential.version,
        trigger=TRIGGER_MANUAL,
        idempotency_key=f"provider-verify:{connection.id}:{uuid.uuid4()}",
        correlation_id=correlation_id,
    )
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="verification_requested",
        connection=connection,
        correlation_id=correlation_id,
        requested=requested,
    )
    db.flush()
    return connection


def rotate_connection_secret(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    connection_id: UUID,
    secret: str,
    correlation_id: str | None = None,
) -> ProviderConnection:
    """Replace the secret. The connection stops being ready until the new secret is verified."""
    connection = _get_locked(db, organization_id=organization_id, connection_id=connection_id)
    if connection.status == ProviderConnection.STATUS_DISCONNECTED:
        raise ConnectionStateError("This connection is disconnected. Create a new connection.")
    requested = _requested(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="rotated",
        connection_id=connection.id,
        provider_key=connection.provider_key,
        correlation_id=correlation_id,
    )
    credential = rotate_provider_credential(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        credential_id=connection.credential_id,
        secret=secret,
        correlation_id=correlation_id,
    )
    _set_verifying(connection, reason=REASON_ROTATED)
    _enqueue_verification(
        db,
        connection=connection,
        credential_version=credential.version,
        trigger=TRIGGER_ROTATED,
        idempotency_key=f"provider-verify:{connection.id}:{uuid.uuid4()}",
        correlation_id=correlation_id,
    )
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="rotated",
        connection=connection,
        correlation_id=correlation_id,
        extra={"credential_version": credential.version},
        requested=requested,
    )
    db.flush()
    return connection


def disconnect_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    connection_id: UUID,
    correlation_id: str | None = None,
) -> ProviderConnection:
    """Revoke the credential and end the connection. Disconnecting twice changes nothing."""
    connection = _get_locked(db, organization_id=organization_id, connection_id=connection_id)
    if connection.status == ProviderConnection.STATUS_DISCONNECTED:
        return connection
    requested = _requested(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="disconnected",
        connection_id=connection.id,
        provider_key=connection.provider_key,
        correlation_id=correlation_id,
    )
    credential = _credential_for(db, connection)
    if credential is not None and credential.status == STATUS_ACTIVE:
        revoke_provider_credential(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            credential_id=credential.id,
            correlation_id=correlation_id,
        )
    connection.status = ProviderConnection.STATUS_DISCONNECTED
    connection.status_reason_code = REASON_DISCONNECTED
    connection.next_verification_at = None
    connection.version += 1
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="disconnected",
        connection=connection,
        correlation_id=correlation_id,
        requested=requested,
    )
    db.flush()
    return connection


def list_attempts(
    db: Session,
    *,
    organization_id: UUID,
    connection_id: UUID,
    limit: int,
) -> list[ProviderVerificationAttempt]:
    get_connection(db, organization_id=organization_id, connection_id=connection_id)
    return list(
        db.scalars(
            select(ProviderVerificationAttempt)
            .where(
                ProviderVerificationAttempt.connection_id == connection_id,
                ProviderVerificationAttempt.organization_id == organization_id,
            )
            .order_by(ProviderVerificationAttempt.attempted_at.desc(), ProviderVerificationAttempt.id)
            .limit(limit)
        )
    )


def schedule_due_verifications(db: Session, *, now: datetime, limit: int = 50) -> int:
    """Queue verification for connections whose next check is due. Returns how many were queued.

    The idempotency key contains the due time, so a connection is queued once per due time even if
    several workers run this sweep.
    """
    interval = timedelta(hours=get_settings().provider_verification_interval_hours)
    due = db.scalars(
        select(ProviderConnection)
        .where(
            ProviderConnection.status.in_(
                [
                    ProviderConnection.STATUS_UNVERIFIED,
                    ProviderConnection.STATUS_DEGRADED,
                    ProviderConnection.STATUS_CONNECTED,
                ]
            ),
            ProviderConnection.next_verification_at.is_not(None),
            ProviderConnection.next_verification_at <= now,
        )
        .order_by(ProviderConnection.next_verification_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    for connection in due:
        credential = _credential_for(db, connection)
        due_at = connection.next_verification_at
        _enqueue_verification(
            db,
            connection=connection,
            credential_version=credential.version if credential is not None else 0,
            trigger=TRIGGER_SCHEDULED,
            idempotency_key=f"provider-verify-due:{connection.id}:{due_at.isoformat()}",
            correlation_id=None,
        )
        # Move the next check out of the window so this sweep does not queue it again.
        connection.next_verification_at = now + interval
    db.flush()
    return len(due)


def backoff_seconds(consecutive_failures: int) -> int:
    capped = min(BASE_BACKOFF_SECONDS * (2 ** max(consecutive_failures - 1, 0)),
                 get_settings().provider_verification_backoff_max_seconds)
    return int(capped)


def record_verification_result(
    db: Session,
    *,
    connection: ProviderConnection,
    credential: ProviderCredential,
    trigger: str,
    outcome: VerificationOutcome,
    reason_code: str | None,
    latency_ms: int,
    adapter_version: str,
    correlation_id: str | None,
    now: datetime,
) -> None:
    """Apply one verification outcome to the connection and write its attempt row.

    Called only by the verification handler, under the connection's row lock.
    """
    settings = get_settings()
    connection.last_attempt_at = now
    db.add(
        ProviderVerificationAttempt(
            id=uuid4(),
            connection_id=connection.id,
            organization_id=connection.organization_id,
            provider_key=connection.provider_key,
            credential_version=credential.version,
            trigger=trigger,
            outcome=outcome.value,
            reason_code=reason_code,
            latency_ms=latency_ms,
            adapter_version=adapter_version,
            correlation_id=correlation_id,
            attempted_at=now,
        )
    )

    if outcome is VerificationOutcome.SUCCEEDED:
        connection.status = ProviderConnection.STATUS_CONNECTED
        connection.status_reason_code = None
        connection.verified_credential_version = credential.version
        connection.last_verified_at = now
        connection.consecutive_failures = 0
        connection.next_verification_at = now + timedelta(hours=settings.provider_verification_interval_hours)
    elif outcome is VerificationOutcome.NOT_VERIFIED:
        # Live access is off. The connection is not usable, and nothing is scheduled.
        connection.status = ProviderConnection.STATUS_UNVERIFIED
        connection.status_reason_code = reason_code
        connection.next_verification_at = None
    elif outcome in (VerificationOutcome.TRANSIENT_FAILURE, VerificationOutcome.TIMED_OUT):
        connection.consecutive_failures += 1
        if connection.consecutive_failures >= settings.provider_verification_failure_threshold:
            connection.status = ProviderConnection.STATUS_FAILED
            connection.status_reason_code = REASON_FAILED_REPEATEDLY
            connection.next_verification_at = None
        else:
            connection.status = ProviderConnection.STATUS_DEGRADED
            connection.status_reason_code = reason_code
            connection.next_verification_at = now + timedelta(
                seconds=backoff_seconds(connection.consecutive_failures)
            )
    else:  # PERMANENT_FAILURE
        connection.consecutive_failures += 1
        connection.status = ProviderConnection.STATUS_FAILED
        connection.status_reason_code = reason_code
        connection.next_verification_at = None
    connection.version += 1


def record_system_failure(
    db: Session,
    *,
    connection: ProviderConnection,
    credential_version: int,
    trigger: str,
    reason_code: str,
    adapter_version: str,
    correlation_id: str | None,
    now: datetime,
) -> None:
    """Mark a connection failed without calling a provider (revoked credential, missing adapter)."""
    connection.last_attempt_at = now
    connection.consecutive_failures += 1
    connection.status = ProviderConnection.STATUS_FAILED
    connection.status_reason_code = reason_code
    connection.next_verification_at = None
    connection.version += 1
    db.add(
        ProviderVerificationAttempt(
            id=uuid4(),
            connection_id=connection.id,
            organization_id=connection.organization_id,
            provider_key=connection.provider_key,
            credential_version=credential_version,
            trigger=trigger,
            outcome=VerificationOutcome.PERMANENT_FAILURE.value,
            reason_code=reason_code,
            latency_ms=0,
            adapter_version=adapter_version,
            correlation_id=correlation_id,
            attempted_at=now,
        )
    )
    _audit(
        db,
        organization_id=connection.organization_id,
        actor_user_id=None,
        action=f"verification_{VerificationOutcome.PERMANENT_FAILURE.value}",
        connection=connection,
        correlation_id=correlation_id,
    )


def audit_verification(
    db: Session,
    *,
    connection: ProviderConnection,
    outcome: VerificationOutcome,
    correlation_id: str | None,
) -> None:
    _audit(
        db,
        organization_id=connection.organization_id,
        actor_user_id=None,
        action=f"verification_{outcome.value}",
        connection=connection,
        correlation_id=correlation_id,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
