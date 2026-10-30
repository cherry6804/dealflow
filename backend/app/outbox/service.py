"""Transactional outbox: enqueue events with the business change, dispatch them later.

Producers call ``enqueue_event`` with the session of the change they describe.
The event is committed if and only if that change commits.

``dispatch_due_events`` claims due events under a lease, runs the handler for
each event inside a savepoint, and records the outcome. A failure rolls back
the handler's writes, schedules a retry with bounded exponential backoff, and
moves the event to ``dead_letter`` after ``max_attempts``.

Delivery is at-least-once. A handler can run again after a crash or after its
lease expires, so handlers must be idempotent and must bound their own I/O.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)

EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
MAX_EVENT_TYPE_LENGTH = 120
MAX_AGGREGATE_TYPE_LENGTH = 80
MAX_AGGREGATE_ID_LENGTH = 120
MAX_IDEMPOTENCY_KEY_LENGTH = 200
MAX_CORRELATION_ID_LENGTH = 64
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_ERROR_LENGTH = 500

EventHandler = Callable[[Session, OutboxEvent], None]
_handlers: dict[str, EventHandler] = {}


class OutboxError(Exception):
    """Base class for outbox failures that callers can handle."""


class InvalidOutboxEventError(OutboxError):
    """The event description is malformed and must not be enqueued."""


class OutboxConflictError(OutboxError):
    """An idempotency key was reused for a different event."""


class UnknownEventTypeError(OutboxError):
    """No handler is registered for the event type."""


@dataclass(frozen=True)
class DispatchResult:
    """Counts for one dispatch cycle."""

    claimed: int = 0
    delivered: int = 0
    retried: int = 0
    dead_lettered: int = 0


def utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_event_type(event_type: str) -> None:
    if len(event_type) > MAX_EVENT_TYPE_LENGTH or not EVENT_TYPE_PATTERN.match(
        event_type
    ):
        raise InvalidOutboxEventError(
            "Event types must be lowercase dotted names such as 'lead.created'."
        )


def _validate_text(name: str, value: str, max_length: int) -> None:
    if not value or not value.strip() or len(value) > max_length:
        raise InvalidOutboxEventError(f"{name} must be 1 to {max_length} characters.")


def register_handler(event_type: str, handler: EventHandler) -> None:
    """Register the handler for one event type. Re-registering the same handler is allowed."""
    _validate_event_type(event_type)
    existing = _handlers.get(event_type)
    if existing is not None and existing is not handler:
        raise OutboxError(
            f"A different handler is already registered for {event_type!r}."
        )
    _handlers[event_type] = handler


def unregister_handler(event_type: str) -> None:
    """Remove a handler. Used by tests and by modules that unload."""
    _handlers.pop(event_type, None)


def enqueue_event(
    db: Session,
    *,
    organization_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
    correlation_id: str | None = None,
    schema_version: int = 1,
    max_attempts: int | None = None,
    available_at: datetime | None = None,
) -> OutboxEvent:
    """Add an event to the caller's transaction.

    The caller must commit. If the caller rolls back, the event is discarded
    with the change it describes. Reusing an idempotency key for the same event
    returns the stored row. Reusing it for a different tenant, type or aggregate
    raises ``OutboxConflictError``.

    Payloads must be JSON-serializable and must not contain secrets, tokens or
    raw personal data that the consumer does not need.
    """
    _validate_event_type(event_type)
    _validate_text("aggregate_type", aggregate_type, MAX_AGGREGATE_TYPE_LENGTH)
    _validate_text("aggregate_id", aggregate_id, MAX_AGGREGATE_ID_LENGTH)
    _validate_text("idempotency_key", idempotency_key, MAX_IDEMPOTENCY_KEY_LENGTH)
    if correlation_id is not None:
        _validate_text("correlation_id", correlation_id, MAX_CORRELATION_ID_LENGTH)
    if schema_version < 1:
        raise InvalidOutboxEventError("schema_version must be at least 1.")
    if max_attempts is not None and max_attempts < 1:
        raise InvalidOutboxEventError("max_attempts must be at least 1.")

    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InvalidOutboxEventError("Payload must be JSON-serializable.") from exc
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise InvalidOutboxEventError("Payload exceeds the outbox size limit.")

    existing = db.scalar(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.organization_id != organization_id
            or existing.event_type != event_type
            or existing.aggregate_id != aggregate_id
        ):
            raise OutboxConflictError(
                "The idempotency key is already used by another event."
            )
        return existing

    settings = get_settings()
    event = OutboxEvent(
        organization_id=organization_id,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=json.loads(encoded),
        status=OutboxEvent.STATUS_PENDING,
        attempts=0,
        max_attempts=max_attempts or settings.outbox_max_attempts,
        available_at=available_at or utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def claim_due_events(
    db: Session,
    *,
    worker_id: str,
    now: datetime,
    limit: int,
    lease_seconds: int,
) -> list[OutboxEvent]:
    """Lease due events to one worker.

    Rows are locked with ``FOR UPDATE SKIP LOCKED`` so concurrent workers never
    claim the same event. An event whose lease expired is claimed again, which
    recovers work from a crashed worker.
    """
    due = or_(
        and_(
            OutboxEvent.status == OutboxEvent.STATUS_PENDING,
            OutboxEvent.available_at <= now,
        ),
        and_(
            OutboxEvent.status == OutboxEvent.STATUS_PROCESSING,
            OutboxEvent.locked_until.is_not(None),
            OutboxEvent.locked_until < now,
        ),
    )
    events = list(
        db.scalars(
            select(OutboxEvent)
            .where(due)
            .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    lease_until = now + timedelta(seconds=lease_seconds)
    for event in events:
        event.status = OutboxEvent.STATUS_PROCESSING
        event.locked_by = worker_id
        event.locked_until = lease_until
        event.attempts += 1
    db.flush()
    return events


def _describe_error(exc: BaseException) -> str:
    """Return a bounded, single-line description. Never includes the traceback."""
    message = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ")
    return message[:MAX_ERROR_LENGTH]


def mark_delivered(event: OutboxEvent, *, now: datetime) -> None:
    event.status = OutboxEvent.STATUS_DELIVERED
    event.delivered_at = now
    event.locked_by = None
    event.locked_until = None
    event.last_error = None


def mark_failed(
    event: OutboxEvent,
    *,
    exc: BaseException,
    now: datetime,
    base_backoff_seconds: int,
    max_backoff_seconds: int,
) -> bool:
    """Record a failed attempt. Return True when the event is dead-lettered."""
    event.last_error = _describe_error(exc)
    event.locked_by = None
    event.locked_until = None
    if event.attempts >= event.max_attempts:
        event.status = OutboxEvent.STATUS_DEAD_LETTER
        return True

    delay = min(base_backoff_seconds * (2 ** (event.attempts - 1)), max_backoff_seconds)
    event.status = OutboxEvent.STATUS_PENDING
    event.available_at = now + timedelta(seconds=delay)
    return False


def dispatch_due_events(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    batch_size: int | None = None,
) -> DispatchResult:
    """Claim a batch of due events and run their handlers once each.

    Each event is handled in its own commit. Lease changes are committed before
    handlers run, so other workers see the claim.
    """
    settings = get_settings()
    cycle_now = now or utcnow()
    claimed = claim_due_events(
        db,
        worker_id=worker_id,
        now=cycle_now,
        limit=batch_size or settings.outbox_batch_size,
        lease_seconds=settings.outbox_lease_seconds,
    )
    db.commit()

    delivered = retried = dead_lettered = 0
    for event in claimed:
        event_id = event.id
        event_type = event.event_type
        handler = _handlers.get(event_type)
        try:
            if handler is None:
                raise UnknownEventTypeError(
                    f"No handler is registered for {event_type!r}."
                )
            savepoint = db.begin_nested()
            try:
                handler(db, event)
                savepoint.commit()
            except Exception:
                savepoint.rollback()
                raise
            mark_delivered(event, now=cycle_now)
            delivered += 1
        # A handler may raise any exception. The worker must record it and keep
        # dispatching other events, so this broad catch is intentional.
        except Exception as exc:  # noqa: BLE001
            is_dead = mark_failed(
                event,
                exc=exc,
                now=cycle_now,
                base_backoff_seconds=settings.outbox_base_backoff_seconds,
                max_backoff_seconds=settings.outbox_max_backoff_seconds,
            )
            if is_dead:
                dead_lettered += 1
            else:
                retried += 1
            logger.warning(
                "Outbox event dispatch failed",
                extra={
                    "outbox_event_id": str(event_id),
                    "event_type": event_type,
                    "dead_lettered": is_dead,
                    "error_type": type(exc).__name__,
                },
            )
        db.commit()

    return DispatchResult(
        claimed=len(claimed),
        delivered=delivered,
        retried=retried,
        dead_lettered=dead_lettered,
    )
