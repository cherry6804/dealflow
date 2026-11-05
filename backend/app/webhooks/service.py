"""Verified inbound webhook ingress (DFR1-012).

The order of work for one delivery is fixed, and each step can stop it:

1. The endpoint is resolved by its identifier from the URL. Its organization and provider come from its row, never from the request.
2. A disabled endpoint, or one linked to a connection that is not connected, refuses the delivery.
3. The signing secret is opened with the provider-secrets cipher. If it cannot be opened, the delivery is refused as a transient
   failure, and the provider may retry.
4. The signature and timestamp are verified. Nothing else about the body is read before this step succeeds.
5. The body is parsed as a strict envelope. A malformed body is refused, and its bytes are not stored.
6. Deduplication checks for an accepted delivery with the same endpoint and provider event ID. The same body is a duplicate, and a
   different body under the same ID is a conflict. Neither is processed again.
7. An accepted delivery stores the redacted envelope and queues one outbox event in the same transaction. The unique index on accepted
   deliveries catches two concurrent copies, and the loser is treated as a duplicate.

Every outcome, including refusals, is recorded as a delivery row and an independent audit record. A refusal stores no body. The
organization context is always the endpoint's.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.attribution import (
    AuditAttribution,
    register_system_actor,
    system_attribution,
    user_attribution,
)
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    persist_independent_audit_event,
)
from app.db.models.inbound_webhook import InboundWebhookDelivery, InboundWebhookEndpoint
from app.db.models.provider_connection import ProviderConnection
from app.governance.execution_gate import actor_permission_granted
from app.outbox.service import PermanentHandlerError, enqueue_event
from app.provider_secrets.cipher import decrypt_secret, encrypt_secret
from app.provider_secrets.errors import (
    ProviderSecretsConfigurationError,
    ProviderSecretsDecryptionError,
)
from app.provider_secrets.key_provider import build_key_provider
from app.provider_secrets.redaction import ProviderSecret
from app.webhooks.envelope import MalformedWebhook, normalize
from app.webhooks.verifier import get_verifier

AUDIT_EVENT = "inbound_webhook"
PERMISSION = "webhook_endpoints.manage"
RECEIVED_EVENT_TYPE = "inbound_webhook.received"
DELIVERY_AGGREGATE = "inbound_webhook_delivery"
WEBHOOK_SYSTEM_ACTOR = register_system_actor("inbound_webhooks")
SECRET_BYTES = 32
MAX_LABEL = 120
PROVIDER_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_TIMESTAMP_HEADER = 20

REASON_NOT_FOUND = "endpoint_not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_DISABLED = "endpoint_disabled"
REASON_CONNECTION_NOT_CONNECTED = "connection_not_connected"
REASON_UNSUPPORTED_VERIFIER = "unsupported_verifier"
REASON_SECRET_UNAVAILABLE = "secret_unavailable"
REASON_CONFLICT = "conflicting_payload"
REASON_TRANSIENT = "temporarily_unavailable"
REASON_INVALID_ENDPOINT = "invalid_endpoint"
REASON_ALREADY_DISABLED = "endpoint_already_disabled"
REASON_NOT_ACTIVE = "endpoint_not_active"


class WebhookError(Exception):
    def __init__(
        self, reason: str, problems: list[str] | None = None, *, status: int = 409
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


@dataclass(frozen=True)
class IngestResult:
    status_code: int
    body: dict[str, Any]


# --- secrets ------------------------------------------------------------------------------------------


def _secret_associated_data(endpoint: InboundWebhookEndpoint) -> bytes:
    return f"inbound_webhook|{endpoint.organization_id}|{endpoint.id}|{endpoint.secret_version}".encode(
        "ascii"
    )


def _seal(endpoint: InboundWebhookEndpoint, secret: str) -> None:
    encrypted = encrypt_secret(
        secret,
        associated_data=_secret_associated_data(endpoint),
        keys=build_key_provider(),
    )
    endpoint.secret_ciphertext = encrypted.ciphertext
    endpoint.secret_key_id = encrypted.key_id
    endpoint.secret_algorithm = encrypted.algorithm


def _open(endpoint: InboundWebhookEndpoint) -> ProviderSecret:
    if (
        endpoint.secret_ciphertext is None
        or endpoint.secret_key_id is None
        or endpoint.secret_algorithm is None
    ):
        raise ProviderSecretsDecryptionError("No signing secret is stored.")
    plaintext = decrypt_secret(
        endpoint.secret_ciphertext,
        key_id=endpoint.secret_key_id,
        algorithm=endpoint.secret_algorithm,
        associated_data=_secret_associated_data(endpoint),
        keys=build_key_provider(),
    )
    return ProviderSecret(plaintext)


def _new_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


# --- audit --------------------------------------------------------------------------------------------


def _audit(
    db: Session,
    *,
    attribution: AuditAttribution,
    endpoint: InboundWebhookEndpoint,
    action: str,
    allowed: bool,
    correlation_id: str,
    metadata: dict[str, Any],
) -> None:
    # Identifiers, outcomes and reason codes only. Bodies, envelopes, secrets and signatures are never written here.
    persist_independent_audit_event(
        db,
        attribution=attribution,
        event_type=AUDIT_EVENT,
        action=action,
        decision="allowed" if allowed else "denied",
        outcome=OUTCOME_COMPLETED if allowed else OUTCOME_DENIED,
        permission_key=PERMISSION,
        resource_type="inbound_webhook_endpoint",
        resource_id=str(endpoint.id),
        correlation_id=correlation_id,
        metadata=metadata,
    )


def _system_audit(
    db: Session,
    endpoint: InboundWebhookEndpoint,
    *,
    action: str,
    allowed: bool,
    correlation_id: str,
    metadata: dict[str, Any],
) -> None:
    _audit(
        db,
        attribution=system_attribution(
            organization_id=endpoint.organization_id, capability=WEBHOOK_SYSTEM_ACTOR
        ),
        endpoint=endpoint,
        action=action,
        allowed=allowed,
        correlation_id=correlation_id,
        metadata=metadata,
    )


# --- endpoint administration --------------------------------------------------------------------------


def _require_manage(db: Session, *, organization_id: UUID, actor_id: UUID) -> None:
    if not actor_permission_granted(
        db, organization_id=organization_id, user_id=actor_id, permission_key=PERMISSION
    ):
        raise WebhookError(REASON_PERMISSION_DENIED, status=403)


def _endpoint_in_org(
    db: Session, *, organization_id: UUID, endpoint_id: UUID, lock: bool = False
) -> InboundWebhookEndpoint:
    query = select(InboundWebhookEndpoint).where(
        InboundWebhookEndpoint.id == endpoint_id,
        InboundWebhookEndpoint.organization_id == organization_id,
    )
    if lock:
        query = query.with_for_update()
    endpoint = db.scalar(query)
    if endpoint is None:
        raise WebhookError(REASON_NOT_FOUND, status=404)
    return endpoint


def list_endpoints(
    db: Session, *, organization_id: UUID, actor_id: UUID
) -> list[InboundWebhookEndpoint]:
    _require_manage(db, organization_id=organization_id, actor_id=actor_id)
    return list(
        db.scalars(
            select(InboundWebhookEndpoint)
            .where(
                InboundWebhookEndpoint.organization_id == organization_id,
            )
            .order_by(InboundWebhookEndpoint.created_at, InboundWebhookEndpoint.id)
        ).all()
    )


def create_endpoint(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    label: str,
    provider_key: str,
    verifier_key: str,
    provider_connection_id: UUID | None,
) -> tuple[InboundWebhookEndpoint, str]:
    """Create an endpoint. Returns it with its signing secret, which is shown once and never stored in plain text."""
    _require_manage(db, organization_id=organization_id, actor_id=actor_id)
    clean_label = label.strip()[:MAX_LABEL]
    if not clean_label:
        raise WebhookError(
            REASON_INVALID_ENDPOINT, ["A label is required."], status=422
        )
    if not PROVIDER_KEY.match(provider_key):
        raise WebhookError(
            REASON_INVALID_ENDPOINT, ["The provider key is not valid."], status=422
        )
    if get_verifier(verifier_key) is None:
        raise WebhookError(
            REASON_UNSUPPORTED_VERIFIER, ["This verifier is not available."], status=422
        )
    if provider_connection_id is not None:
        connection = db.scalar(
            select(ProviderConnection).where(
                ProviderConnection.id == provider_connection_id,
                ProviderConnection.organization_id == organization_id,
            )
        )
        if (
            connection is None
            or connection.provider_key != provider_key
            or connection.status != "connected"
        ):
            raise WebhookError(
                REASON_CONNECTION_NOT_CONNECTED,
                [
                    "The linked connection must belong to this organization, match the provider and be connected."
                ],
                status=422,
            )

    # The identifier is fixed before sealing, because the ciphertext is bound to it.
    endpoint = InboundWebhookEndpoint(
        id=uuid.uuid4(),
        organization_id=organization_id,
        label=clean_label,
        provider_key=provider_key,
        verifier_key=verifier_key,
        status=InboundWebhookEndpoint.STATUS_ACTIVE,
        provider_connection_id=provider_connection_id,
        secret_version=1,
        created_by_user_id=actor_id,
    )
    secret = _new_secret()
    _seal(endpoint, secret)
    db.add(endpoint)
    db.flush()
    _audit(
        db,
        attribution=user_attribution(
            organization_id=organization_id, actor_user_id=actor_id
        ),
        endpoint=endpoint,
        action="endpoint_created",
        allowed=True,
        correlation_id=uuid.uuid4().hex,
        metadata={
            "provider_key": provider_key,
            "verifier_key": verifier_key,
            "linked_connection": provider_connection_id is not None,
        },
    )
    return endpoint, secret


def rotate_secret(
    db: Session, *, organization_id: UUID, actor_id: UUID, endpoint_id: UUID
) -> tuple[InboundWebhookEndpoint, str]:
    """Replace the signing secret. The old secret stops working at once, so the sender must be updated first."""
    _require_manage(db, organization_id=organization_id, actor_id=actor_id)
    endpoint = _endpoint_in_org(
        db, organization_id=organization_id, endpoint_id=endpoint_id, lock=True
    )
    if endpoint.status != InboundWebhookEndpoint.STATUS_ACTIVE:
        raise WebhookError(REASON_NOT_ACTIVE, status=409)
    endpoint.secret_version += 1
    secret = _new_secret()
    _seal(endpoint, secret)
    endpoint.rotated_at = datetime.now(UTC)
    endpoint.updated_at = datetime.now(UTC)
    db.flush()
    _audit(
        db,
        attribution=user_attribution(
            organization_id=organization_id, actor_user_id=actor_id
        ),
        endpoint=endpoint,
        action="secret_rotated",
        allowed=True,
        correlation_id=uuid.uuid4().hex,
        metadata={"version": endpoint.secret_version},
    )
    return endpoint, secret


def disable_endpoint(
    db: Session, *, organization_id: UUID, actor_id: UUID, endpoint_id: UUID
) -> InboundWebhookEndpoint:
    """Disable the endpoint and destroy its stored secret. Later deliveries are refused."""
    _require_manage(db, organization_id=organization_id, actor_id=actor_id)
    endpoint = _endpoint_in_org(
        db, organization_id=organization_id, endpoint_id=endpoint_id, lock=True
    )
    if endpoint.status == InboundWebhookEndpoint.STATUS_DISABLED:
        raise WebhookError(REASON_ALREADY_DISABLED, status=409)
    endpoint.status = InboundWebhookEndpoint.STATUS_DISABLED
    endpoint.secret_ciphertext = None
    endpoint.secret_key_id = None
    endpoint.secret_algorithm = None
    endpoint.disabled_by_user_id = actor_id
    endpoint.disabled_at = datetime.now(UTC)
    endpoint.updated_at = datetime.now(UTC)
    db.flush()
    _audit(
        db,
        attribution=user_attribution(
            organization_id=organization_id, actor_user_id=actor_id
        ),
        endpoint=endpoint,
        action="endpoint_disabled",
        allowed=True,
        correlation_id=uuid.uuid4().hex,
        metadata={},
    )
    return endpoint


# --- ingress ------------------------------------------------------------------------------------------


def _record(
    db: Session,
    endpoint: InboundWebhookEndpoint,
    *,
    outcome: str,
    correlation_id: str,
    body_sha256: str,
    body_bytes: int,
    reason: str | None = None,
    signature_verified: bool = False,
    timestamp_header: str | None = None,
    provider_event_id: str | None = None,
    event_type: str | None = None,
    occurred_at: datetime | None = None,
    envelope: dict[str, Any] | None = None,
    outbox_event_id: UUID | None = None,
    now: datetime,
) -> InboundWebhookDelivery:
    row = InboundWebhookDelivery(
        organization_id=endpoint.organization_id,
        endpoint_id=endpoint.id,
        outcome=outcome,
        reason_code=reason,
        signature_verified=signature_verified,
        timestamp_header=timestamp_header[:MAX_TIMESTAMP_HEADER]
        if timestamp_header
        else None,
        body_sha256=body_sha256,
        body_bytes=body_bytes,
        provider_key=endpoint.provider_key,
        provider_event_id=provider_event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        envelope=envelope,
        outbox_event_id=outbox_event_id,
        received_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _refuse(
    db: Session,
    endpoint: InboundWebhookEndpoint,
    *,
    reason: str,
    status_code: int,
    correlation_id: str,
    body_sha256: str,
    body_bytes: int,
    now: datetime,
    signature_verified: bool = False,
    timestamp_header: str | None = None,
) -> IngestResult:
    """Record a refusal, commit it, and return the response. Refusals keep no body."""
    _record(
        db,
        endpoint,
        outcome=InboundWebhookDelivery.OUTCOME_REJECTED,
        reason=reason,
        correlation_id=correlation_id,
        body_sha256=body_sha256,
        body_bytes=body_bytes,
        signature_verified=signature_verified,
        timestamp_header=timestamp_header,
        now=now,
    )
    _system_audit(
        db,
        endpoint,
        action="delivery_rejected",
        allowed=False,
        correlation_id=correlation_id,
        metadata={"reason": reason, "body_bytes": body_bytes},
    )
    db.commit()
    return IngestResult(
        status_code=status_code, body={"status": "rejected", "reason": reason}
    )


def _existing_accepted(
    db: Session, endpoint: InboundWebhookEndpoint, provider_event_id: str
) -> InboundWebhookDelivery | None:
    return db.scalar(
        select(InboundWebhookDelivery).where(
            InboundWebhookDelivery.endpoint_id == endpoint.id,
            InboundWebhookDelivery.provider_event_id == provider_event_id,
            InboundWebhookDelivery.outcome == InboundWebhookDelivery.OUTCOME_ACCEPTED,
        )
    )


def _duplicate_or_conflict(
    db: Session,
    endpoint: InboundWebhookEndpoint,
    existing: InboundWebhookDelivery,
    *,
    body_sha256: str,
    body_bytes: int,
    correlation_id: str,
    provider_event_id: str,
    event_type: str,
    now: datetime,
) -> IngestResult:
    same = existing.body_sha256 == body_sha256
    outcome = (
        InboundWebhookDelivery.OUTCOME_DUPLICATE
        if same
        else InboundWebhookDelivery.OUTCOME_CONFLICT
    )
    _record(
        db,
        endpoint,
        outcome=outcome,
        reason=None if same else REASON_CONFLICT,
        correlation_id=correlation_id,
        body_sha256=body_sha256,
        body_bytes=body_bytes,
        signature_verified=True,
        provider_event_id=provider_event_id,
        event_type=event_type,
        now=now,
    )
    _system_audit(
        db,
        endpoint,
        action="delivery_" + outcome,
        allowed=same,
        correlation_id=correlation_id,
        metadata={
            "provider_event_id": provider_event_id,
            "first_delivery_id": str(existing.id),
        },
    )
    db.commit()
    if same:
        return IngestResult(
            status_code=200,
            body={"status": "duplicate", "delivery_id": str(existing.id)},
        )
    return IngestResult(
        status_code=409, body={"status": "conflict", "reason": REASON_CONFLICT}
    )


def ingest(
    db: Session,
    *,
    endpoint_id: UUID,
    timestamp_header: str | None,
    signature_header: str | None,
    body: bytes,
    now: datetime,
    replay_window_seconds: int,
) -> IngestResult:
    """Verify, normalise and queue one delivery. Every outcome is committed before this returns."""
    correlation_id = uuid.uuid4().hex
    body_sha256 = hashlib.sha256(body).hexdigest()
    body_bytes = len(body)
    endpoint = db.get(InboundWebhookEndpoint, endpoint_id)
    if endpoint is None:
        return IngestResult(
            status_code=404, body={"status": "rejected", "reason": REASON_NOT_FOUND}
        )

    common = {
        "correlation_id": correlation_id,
        "body_sha256": body_sha256,
        "body_bytes": body_bytes,
        "now": now,
    }

    if endpoint.status != InboundWebhookEndpoint.STATUS_ACTIVE:
        return _refuse(db, endpoint, reason=REASON_DISABLED, status_code=403, **common)

    if endpoint.provider_connection_id is not None:
        connection = db.get(ProviderConnection, endpoint.provider_connection_id)
        if (
            connection is None
            or connection.organization_id != endpoint.organization_id
            or connection.provider_key != endpoint.provider_key
            or connection.status != "connected"
        ):
            return _refuse(
                db,
                endpoint,
                reason=REASON_CONNECTION_NOT_CONNECTED,
                status_code=403,
                **common,
            )

    verifier = get_verifier(endpoint.verifier_key)
    if verifier is None:
        return _refuse(
            db, endpoint, reason=REASON_UNSUPPORTED_VERIFIER, status_code=403, **common
        )

    try:
        secret = _open(endpoint)
    except (ProviderSecretsConfigurationError, ProviderSecretsDecryptionError):
        # Fail closed: nothing is processed. The record shows the failure, and the provider may retry once this is fixed.
        _record(
            db,
            endpoint,
            outcome=InboundWebhookDelivery.OUTCOME_FAILED,
            reason=REASON_SECRET_UNAVAILABLE,
            correlation_id=correlation_id,
            body_sha256=body_sha256,
            body_bytes=body_bytes,
            now=now,
        )
        _system_audit(
            db,
            endpoint,
            action="delivery_failed",
            allowed=False,
            correlation_id=correlation_id,
            metadata={"reason": REASON_SECRET_UNAVAILABLE},
        )
        db.commit()
        return IngestResult(
            status_code=503,
            body={"status": "failed", "reason": REASON_SECRET_UNAVAILABLE},
        )

    verification = verifier.verify(
        secret=secret,
        timestamp_header=timestamp_header,
        signature_header=signature_header,
        body=body,
        now_epoch=int(now.timestamp()),
        replay_window_seconds=replay_window_seconds,
    )
    if not verification.verified:
        return _refuse(
            db,
            endpoint,
            reason=verification.reason or "invalid_signature",
            status_code=401,
            timestamp_header=timestamp_header,
            **common,
        )

    try:
        event = normalize(body)
    except MalformedWebhook as error:
        # The sender is authentic but the body is not a valid envelope. Its bytes are not kept.
        return _refuse(
            db,
            endpoint,
            reason=error.reason,
            status_code=400,
            signature_verified=True,
            timestamp_header=timestamp_header,
            **common,
        )

    existing = _existing_accepted(db, endpoint, event.provider_event_id)
    if existing is not None:
        return _duplicate_or_conflict(
            db,
            endpoint,
            existing,
            body_sha256=body_sha256,
            body_bytes=body_bytes,
            correlation_id=correlation_id,
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            now=now,
        )

    envelope = event.envelope(
        provider_key=endpoint.provider_key,
        received_at=now,
        correlation_id=correlation_id,
    )
    try:
        with db.begin_nested():
            row = _record(
                db,
                endpoint,
                outcome=InboundWebhookDelivery.OUTCOME_ACCEPTED,
                correlation_id=correlation_id,
                body_sha256=body_sha256,
                body_bytes=body_bytes,
                signature_verified=True,
                timestamp_header=timestamp_header,
                provider_event_id=event.provider_event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                envelope=envelope,
                now=now,
            )
            queued = enqueue_event(
                db,
                organization_id=endpoint.organization_id,
                event_type=RECEIVED_EVENT_TYPE,
                aggregate_type=DELIVERY_AGGREGATE,
                aggregate_id=str(row.id),
                idempotency_key=f"inbound_webhook:{endpoint.id}:{event.provider_event_id}",
                payload={"delivery_id": str(row.id)},
                correlation_id=correlation_id,
            )
            row.outbox_event_id = queued.id
            db.flush()
    except IntegrityError:
        # A concurrent copy of the same delivery was accepted first. Nothing from this attempt was written.
        winner = _existing_accepted(db, endpoint, event.provider_event_id)
        if winner is None:
            raise
        return _duplicate_or_conflict(
            db,
            endpoint,
            winner,
            body_sha256=body_sha256,
            body_bytes=body_bytes,
            correlation_id=correlation_id,
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            now=now,
        )

    _system_audit(
        db,
        endpoint,
        action="delivery_accepted",
        allowed=True,
        correlation_id=correlation_id,
        metadata={
            "delivery_id": str(row.id),
            "provider_event_id": event.provider_event_id,
            "event_type": event.event_type,
        },
    )
    db.commit()
    return IngestResult(
        status_code=202,
        body={
            "status": "accepted",
            "delivery_id": str(row.id),
            "correlation_id": correlation_id,
        },
    )


# --- outbox handler -----------------------------------------------------------------------------------


def handle_delivery_received(db: Session, event: Any) -> None:
    """Mark an accepted delivery as handled. Idempotent. No business effect is applied in this story."""
    payload = getattr(event, "payload", None) or {}
    try:
        delivery_id = UUID(str(payload["delivery_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentHandlerError(
            "The delivery event is invalid.", reason_code="invalid_delivery_payload"
        ) from exc
    row = db.scalar(
        select(InboundWebhookDelivery)
        .where(
            InboundWebhookDelivery.id == delivery_id,
            InboundWebhookDelivery.organization_id == event.organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise PermanentHandlerError(
            "The delivery was not found.", reason_code="delivery_not_found"
        )
    if row.handled_at is not None:
        return
    row.handled_at = datetime.now(UTC)
    db.flush()


__all__ = [
    "PERMISSION",
    "RECEIVED_EVENT_TYPE",
    "IngestResult",
    "WebhookError",
    "create_endpoint",
    "disable_endpoint",
    "handle_delivery_received",
    "ingest",
    "list_endpoints",
    "rotate_secret",
]
