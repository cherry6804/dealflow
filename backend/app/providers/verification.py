"""Outbox handler that verifies a provider connection (ADR-0032, decision D5).

Runs in the WS3 worker, under the outbox's per-event transaction. The handler:

* locks the connection row, so two checks for one connection run one after the other;
* skips a check whose credential version is no longer current (a newer check is already queued);
* fails a connection whose credential was revoked, without contacting the provider;
* decrypts the secret only for the adapter call, and drops the reference afterwards;
* records the outcome as an attempt and as the connection's new status.

Permanent conditions are recorded as outcomes and the handler returns normally, so the event is
delivered and the recorded status is kept. Only infrastructure failures raise, so the outbox retries
them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.outbox_event import OutboxEvent
from app.db.models.provider_connection import ProviderConnection
from app.outbox.service import PermanentHandlerError, register_handler
from app.provider_secrets.service import STATUS_ACTIVE, get_provider_secret_for_gateway
from app.providers.adapters import adapter_for
from app.providers.base import VerificationOutcome
from app.providers.service import (
    PROVIDER_VERIFICATION_EVENT,
    REASON_ADAPTER_NOT_IMPLEMENTED,
    REASON_CREDENTIAL_REVOKED,
    audit_verification,
    credential_for_connection,
    record_system_failure,
    record_verification_result,
)

_TRIGGERS = frozenset({"created", "rotated", "manual", "scheduled"})


def _payload(event: OutboxEvent) -> tuple[UUID, int, str]:
    payload = event.payload
    connection_id = payload.get("connection_id")
    credential_version = payload.get("credential_version")
    trigger = payload.get("trigger")
    if (
        not isinstance(connection_id, str)
        or not isinstance(credential_version, int)
        or not isinstance(trigger, str)
        or trigger not in _TRIGGERS
    ):
        raise PermanentHandlerError("Verification payload is invalid.", reason_code="invalid_verification_payload")
    try:
        return UUID(connection_id), credential_version, trigger
    except ValueError:
        raise PermanentHandlerError(
            "Verification payload is invalid.", reason_code="invalid_verification_payload"
        ) from None


def handle_verification_requested(db: Session, event: OutboxEvent) -> None:
    connection_id, expected_version, trigger = _payload(event)
    now = datetime.now(UTC)

    connection = db.scalar(
        select(ProviderConnection)
        .where(
            ProviderConnection.id == connection_id,
            ProviderConnection.organization_id == event.organization_id,
        )
        .with_for_update()
    )
    if connection is None:
        raise PermanentHandlerError("The connection for this check no longer exists.", reason_code="connection_not_found")
    if connection.status == ProviderConnection.STATUS_DISCONNECTED:
        return

    credential = credential_for_connection(db, connection)
    if credential is None or credential.status != STATUS_ACTIVE:
        record_system_failure(
            db,
            connection=connection,
            credential_version=expected_version,
            trigger=trigger,
            reason_code=REASON_CREDENTIAL_REVOKED,
            adapter_version="none",
            correlation_id=event.correlation_id,
            now=now,
        )
        return
    if credential.version != expected_version:
        # Superseded by a rotation, whose own check is already queued.
        return

    adapter = adapter_for(connection.provider_key)
    if adapter is None:
        record_system_failure(
            db,
            connection=connection,
            credential_version=credential.version,
            trigger=trigger,
            reason_code=REASON_ADAPTER_NOT_IMPLEMENTED,
            adapter_version="none",
            correlation_id=event.correlation_id,
            now=now,
        )
        return

    # Infrastructure errors (missing key, decryption failure) propagate, so the outbox retries.
    secret = get_provider_secret_for_gateway(
        db,
        organization_id=connection.organization_id,
        provider_key=connection.provider_key,
    )
    result = adapter.verify(secret.reveal())
    del secret

    record_verification_result(
        db,
        connection=connection,
        credential=credential,
        trigger=trigger,
        outcome=result.outcome,
        reason_code=result.reason_code,
        latency_ms=result.latency_ms,
        adapter_version=result.adapter_version,
        correlation_id=event.correlation_id,
        now=now,
    )
    audit_verification(db, connection=connection, outcome=result.outcome, correlation_id=event.correlation_id)


def register_provider_handlers() -> None:
    """Register the provider verification handler. Safe to call more than once."""
    register_handler(PROVIDER_VERIFICATION_EVENT, handle_verification_requested)


__all__ = [
    "VerificationOutcome",
    "handle_verification_requested",
    "register_provider_handlers",
]
