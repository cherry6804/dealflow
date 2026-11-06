"""Transactional outbox: enqueue events with the business change, dispatch them later.

Producers call ``enqueue_event`` with the session of the change they describe.
The event is committed if and only if that change commits.

``dispatch_due_events`` claims due events under a lease that carries a fresh
``claim_token``. For each event it locks the row while the claim still belongs to
this worker, runs the handler inside a savepoint, and records the outcome with a
fenced update. A worker whose claim has been taken over records nothing and its
handler writes are rolled back. Retryable failures back off exponentially with
optional jitter. Permanent configuration errors go straight to ``dead_letter``
with a reason code, and so do events that exhaust ``max_attempts``.

Delivery is at-least-once. A handler can run again after a crash or after its
lease expires, so handlers must be idempotent. Side effects outside the database
are not covered by the transaction and can repeat after a crash.
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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
MAX_REASON_CODE_LENGTH = 64

DEAD_LETTER_MAX_ATTEMPTS = "max_attempts_exhausted"
DEAD_LETTER_NO_HANDLER = "no_handler_registered"
DEAD_LETTER_PERMANENT = "permanent_error"

# Outcomes recorded by ``dispatch_due_events``.
OUTCOME_DELIVERED = "delivered"
OUTCOME_RETRIED = "retried"
OUTCOME_DEAD_LETTERED = "dead_lettered"
OUTCOME_LEASE_LOST = "lease_lost"
OUTCOME_RELEASED = "released"

EventHandler = Callable[[Session, OutboxEvent], None]
_handlers: dict[str, EventHandler] = {}


class OutboxError(Exception):
    """Base class for outbox failures that callers can handle."""


class InvalidOutboxEventError(OutboxError):
    """The event description is malformed and must not be enqueued."""


class OutboxConflictError(OutboxError):
    """An idempotency key was reused for a different event."""


class PermanentHandlerError(OutboxError):
    """A handler failure that another attempt cannot fix, such as a missing configuration.

    The event is dead-lettered at once with ``reason_code``. An operator replays it after the
    configuration is corrected.
    """

    def __init__(self, message: str, *, reason_code: str = DEAD_LETTER_PERMANENT) -> None:
        super().__init__(message)
        if not reason_code or len(reason_code) > MAX_REASON_CODE_LENGTH:
            raise ValueError("reason_code must be 1 to 64 characters.")
        self.reason_code = reason_code


class UnknownEventTypeError(PermanentHandlerError):
    """No handler is registered for the event type in this worker process."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason_code=DEAD_LETTER_NO_HANDLER)


class HandlerTimeoutError(Exception):
    """A handler's database work exceeded the handler timeout. The database cancelled it (DFR1-013)."""


@dataclass(frozen=True)
class DispatchResult:
    """Counts for one dispatch cycle."""

    claimed: int = 0
    delivered: int = 0
    retried: int = 0
    dead_lettered: int = 0
    lease_lost: int = 0
    released: int = 0
    timed_out: int = 0


@dataclass(frozen=True)
class _Claim:
    """The claim-time facts a worker needs after its transactions have ended."""

    event: OutboxEvent
    event_id: UUID
    token: UUID
    attempts: int
    max_attempts: int
    event_type: str
    organization_id: UUID
    correlation_id: str | None


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


def registered_event_types() -> frozenset[str]:
    """Event types this process can dispatch. Used by readiness and by operator replay."""
    return frozenset(_handlers)


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
    raises ``OutboxConflictError``, which does not say which of those differed.

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

    existing = _existing_for_key(db, idempotency_key)
    if existing is not None:
        return _matching_or_conflict(existing, organization_id, event_type, aggregate_id)

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
    try:
        # A savepoint keeps the caller's transaction usable if another producer inserts the same
        # key between the lookup above and this insert.
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        existing = _existing_for_key(db, idempotency_key)
        if existing is None:
            raise
        return _matching_or_conflict(existing, organization_id, event_type, aggregate_id)
    return event


def _existing_for_key(db: Session, idempotency_key: str) -> OutboxEvent | None:
    return db.scalar(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
    )


def _matching_or_conflict(
    existing: OutboxEvent,
    organization_id: UUID,
    event_type: str,
    aggregate_id: str,
) -> OutboxEvent:
    if (
        existing.organization_id != organization_id
        or existing.event_type != event_type
        or existing.aggregate_id != aggregate_id
    ):
        raise OutboxConflictError("The idempotency key is already used by another event.")
    return existing


def backoff_seconds(
    attempts: int,
    *,
    base_backoff_seconds: int,
    max_backoff_seconds: int,
    rng: random.Random | None = None,
) -> int:
    """Delay before the next attempt. With ``rng`` the delay is jittered into [50%, 100%]."""
    capped = min(base_backoff_seconds * (2 ** (attempts - 1)), max_backoff_seconds)
    if rng is None:
        return capped
    return max(1, int(capped * rng.uniform(0.5, 1.0)))


def claim_due_events(
    db: Session,
    *,
    worker_id: str,
    now: datetime,
    limit: int,
    lease_seconds: int,
) -> list[OutboxEvent]:
    """Lease due events to one worker and give each claim a new token.

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
        event.claim_token = uuid4()
        event.attempts += 1
    db.flush()
    return events


_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s()-]{7,}\d")


def _redact_phone(match: re.Match[str]) -> str:
    # Dates and counts are shorter than a phone number. Only a run of ten or more digits is redacted.
    return "[phone]" if sum(character.isdigit() for character in match.group()) >= 10 else match.group()


def _describe_error(exc: BaseException) -> str:
    """Return a bounded, single-line description. Never includes the traceback.

    Database error messages echo the failing row, for example an email address in a unique-key violation, so for
    database errors only the exception type is stored. Other messages are kept for operators, with email addresses
    and phone-like numbers replaced (DFR1-050), because a validation message can name the value it rejected.
    """
    if isinstance(exc, SQLAlchemyError):
        return f"{type(exc).__name__}: database error (details withheld)"
    message = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ")
    message = _PHONE_PATTERN.sub(_redact_phone, _EMAIL_PATTERN.sub("[email]", message))
    return message[:MAX_ERROR_LENGTH]


def delivered_values(*, now: datetime) -> dict[str, object]:
    """Column values that record a successful delivery."""
    return {
        "status": OutboxEvent.STATUS_DELIVERED,
        "delivered_at": now,
        "locked_by": None,
        "locked_until": None,
        "claim_token": None,
        "last_error": None,
        "dead_letter_reason": None,
    }


def failure_values(
    *,
    exc: BaseException,
    attempts: int,
    max_attempts: int,
    now: datetime,
    base_backoff_seconds: int,
    max_backoff_seconds: int,
    rng: random.Random | None = None,
) -> tuple[dict[str, object], bool]:
    """Column values that record a failed attempt, and whether the event is now dead-lettered."""
    values: dict[str, object] = {
        "last_error": _describe_error(exc),
        "locked_by": None,
        "locked_until": None,
        "claim_token": None,
    }
    if isinstance(exc, PermanentHandlerError):
        values["status"] = OutboxEvent.STATUS_DEAD_LETTER
        values["dead_letter_reason"] = exc.reason_code
        return values, True
    if attempts >= max_attempts:
        values["status"] = OutboxEvent.STATUS_DEAD_LETTER
        values["dead_letter_reason"] = DEAD_LETTER_MAX_ATTEMPTS
        return values, True

    delay = backoff_seconds(
        attempts,
        base_backoff_seconds=base_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
        rng=rng,
    )
    values["status"] = OutboxEvent.STATUS_PENDING
    values["available_at"] = now + timedelta(seconds=delay)
    return values, False


def mark_delivered(event: OutboxEvent, *, now: datetime) -> None:
    for name, value in delivered_values(now=now).items():
        setattr(event, name, value)


def mark_failed(
    event: OutboxEvent,
    *,
    exc: BaseException,
    now: datetime,
    base_backoff_seconds: int,
    max_backoff_seconds: int,
    rng: random.Random | None = None,
) -> bool:
    """Record a failed attempt on an in-memory event. Return True when it is dead-lettered."""
    values, is_dead = failure_values(
        exc=exc,
        attempts=event.attempts,
        max_attempts=event.max_attempts,
        now=now,
        base_backoff_seconds=base_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
        rng=rng,
    )
    for name, value in values.items():
        setattr(event, name, value)
    return is_dead


def _owns_claim(event_id: UUID, worker_id: str, token: UUID) -> Any:
    return and_(
        OutboxEvent.id == event_id,
        OutboxEvent.status == OutboxEvent.STATUS_PROCESSING,
        OutboxEvent.locked_by == worker_id,
        OutboxEvent.claim_token == token,
    )


def lock_claim(db: Session, *, event_id: UUID, worker_id: str, token: UUID) -> bool:
    """Lock the event row if this worker still holds the claim. Return False when the lease was lost.

    The lock is held until the transaction ends. Other workers skip locked rows, so they cannot
    reclaim the event while this worker's handler runs.
    """
    locked = db.scalar(
        select(OutboxEvent.id)
        .where(_owns_claim(event_id, worker_id, token))
        .with_for_update()
    )
    return locked is not None


def apply_claim_transition(
    db: Session,
    *,
    event_id: UUID,
    worker_id: str,
    token: UUID,
    values: Mapping[str, object],
) -> bool:
    """Write an outcome only if this worker still holds the claim. Return False otherwise."""
    result = db.execute(
        update(OutboxEvent)
        .where(_owns_claim(event_id, worker_id, token))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def release_claim(
    db: Session,
    *,
    event_id: UUID,
    worker_id: str,
    token: UUID,
    now: datetime,
) -> bool:
    """Return an unprocessed claim to the queue without penalty (used on graceful shutdown)."""
    return apply_claim_transition(
        db,
        event_id=event_id,
        worker_id=worker_id,
        token=token,
        values={
            "status": OutboxEvent.STATUS_PENDING,
            "available_at": now,
            "locked_by": None,
            "locked_until": None,
            "claim_token": None,
            "attempts": OutboxEvent.attempts - 1,
        },
    )


def _snapshot(event: OutboxEvent) -> _Claim:
    return _Claim(
        event=event,
        event_id=event.id,
        token=event.claim_token,
        attempts=event.attempts,
        max_attempts=event.max_attempts,
        event_type=event.event_type,
        organization_id=event.organization_id,
        correlation_id=event.correlation_id,
    )


def _log_outcome(
    level: int,
    message: str,
    *,
    worker_id: str,
    claim: _Claim,
    outcome: str,
    dead_letter_reason: str | None = None,
    error_type: str | None = None,
) -> None:
    logger.log(
        level,
        message,
        extra={
            "worker_id": worker_id,
            "outbox_event_id": str(claim.event_id),
            "event_type": claim.event_type,
            "organization_id": str(claim.organization_id),
            "correlation_id": claim.correlation_id or str(claim.event_id),
            "attempt": claim.attempts,
            "outcome": outcome,
            "dead_letter_reason": dead_letter_reason,
            "error_type": error_type,
        },
    )


def _is_statement_timeout(exc: BaseException) -> bool:
    """True when PostgreSQL cancelled a statement because of statement_timeout."""
    original = getattr(exc, "orig", None)
    if type(original).__name__ == "QueryCanceled":
        return True
    return "statement timeout" in str(original or "").lower()


def _apply_handler_timeout(db: Session, timeout_ms: int) -> None:
    """Bound the database work of one handler. The setting is transaction-scoped (SET LOCAL).

    Only PostgreSQL supports statement_timeout. Other dialects are not used for production.
    """
    if db.get_bind().dialect.name == "postgresql":
        # timeout_ms is an integer from validated settings, so it is not user input.
        db.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))


def _process_claim(
    db: Session,
    claim: _Claim,
    *,
    worker_id: str,
    now: datetime,
    settings_values: Mapping[str, int],
    rng: random.Random | None,
) -> tuple[str, bool]:
    """Run one claimed event and record its outcome. Return the outcome name."""
    handler = _handlers.get(claim.event_type)
    try:
        if handler is None:
            raise UnknownEventTypeError(f"No handler is registered for {claim.event_type!r}.")
        if not lock_claim(db, event_id=claim.event_id, worker_id=worker_id, token=claim.token):
            db.rollback()
            _log_outcome(
                logging.WARNING,
                "Outbox claim was lost before the handler ran",
                worker_id=worker_id,
                claim=claim,
                outcome=OUTCOME_LEASE_LOST,
            )
            return OUTCOME_LEASE_LOST, False

        savepoint = db.begin_nested()
        try:
            _apply_handler_timeout(db, settings_values["handler_timeout_ms"])
            handler(db, claim.event)
            savepoint.commit()
        except Exception as handler_exc:
            savepoint.rollback()
            if _is_statement_timeout(handler_exc):
                raise HandlerTimeoutError(
                    f"Handler exceeded {settings_values['handler_timeout_ms'] // 1000}s; "
                    "database work was cancelled."
                ) from None
            raise

        if not apply_claim_transition(
            db,
            event_id=claim.event_id,
            worker_id=worker_id,
            token=claim.token,
            values=delivered_values(now=now),
        ):
            db.rollback()
            _log_outcome(
                logging.WARNING,
                "Outbox claim was lost while the handler ran; its writes were discarded",
                worker_id=worker_id,
                claim=claim,
                outcome=OUTCOME_LEASE_LOST,
            )
            return OUTCOME_LEASE_LOST, False
        db.commit()
        _log_outcome(logging.INFO, "Outbox event delivered", worker_id=worker_id, claim=claim,
                     outcome=OUTCOME_DELIVERED)
        return OUTCOME_DELIVERED, False
    # A handler may raise any exception. The worker must record it and keep
    # dispatching other events, so this broad catch is intentional.
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        values, is_dead = failure_values(
            exc=exc,
            attempts=claim.attempts,
            max_attempts=claim.max_attempts,
            now=now,
            base_backoff_seconds=settings_values["base_backoff_seconds"],
            max_backoff_seconds=settings_values["max_backoff_seconds"],
            rng=rng,
        )
        if not apply_claim_transition(
            db,
            event_id=claim.event_id,
            worker_id=worker_id,
            token=claim.token,
            values=values,
        ):
            db.rollback()
            _log_outcome(
                logging.WARNING,
                "Outbox claim was lost before the failure was recorded",
                worker_id=worker_id,
                claim=claim,
                outcome=OUTCOME_LEASE_LOST,
            )
            return OUTCOME_LEASE_LOST, False
        db.commit()

        reason = values.get("dead_letter_reason")
        outcome = OUTCOME_DEAD_LETTERED if is_dead else OUTCOME_RETRIED
        _log_outcome(
            logging.WARNING,
            "Outbox event dispatch failed",
            worker_id=worker_id,
            claim=claim,
            outcome=outcome,
            dead_letter_reason=reason if isinstance(reason, str) else None,
            error_type=type(exc).__name__,
        )
        return outcome, isinstance(exc, HandlerTimeoutError)


def dispatch_due_events(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    batch_size: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    rng: random.Random | None = None,
) -> DispatchResult:
    """Claim a batch of due events and run their handlers once each.

    Each event is handled in its own transaction. The claim commits before any handler
    runs, so other workers see it. When ``should_stop`` returns True, the events not yet
    started are released back to the queue without a failed attempt.
    """
    settings = get_settings()
    if settings.outbox_handler_timeout_seconds >= settings.outbox_lease_seconds:
        raise ValueError("outbox_handler_timeout_seconds must be shorter than outbox_lease_seconds.")
    cycle_now = now or utcnow()
    if rng is None and settings.outbox_jitter_enabled:
        rng = random.Random()
    settings_values = {
        "base_backoff_seconds": settings.outbox_base_backoff_seconds,
        "max_backoff_seconds": settings.outbox_max_backoff_seconds,
        "handler_timeout_ms": settings.outbox_handler_timeout_seconds * 1000,
    }

    claimed = claim_due_events(
        db,
        worker_id=worker_id,
        now=cycle_now,
        limit=batch_size or settings.outbox_batch_size,
        lease_seconds=settings.outbox_lease_seconds,
    )
    claims = [_snapshot(event) for event in claimed]
    db.commit()

    counts = {
        OUTCOME_DELIVERED: 0,
        OUTCOME_RETRIED: 0,
        OUTCOME_DEAD_LETTERED: 0,
        OUTCOME_LEASE_LOST: 0,
        OUTCOME_RELEASED: 0,
    }
    timed_out = 0
    for index, claim in enumerate(claims):
        if should_stop is not None and should_stop():
            for remaining in claims[index:]:
                release_claim(
                    db,
                    event_id=remaining.event_id,
                    worker_id=worker_id,
                    token=remaining.token,
                    now=cycle_now,
                )
                counts[OUTCOME_RELEASED] += 1
            db.commit()
            break
        outcome, claim_timed_out = _process_claim(
            db,
            claim,
            worker_id=worker_id,
            now=cycle_now,
            settings_values=settings_values,
            rng=rng,
        )
        counts[outcome] += 1
        timed_out += int(claim_timed_out)

    return DispatchResult(
        claimed=len(claims),
        delivered=counts[OUTCOME_DELIVERED],
        retried=counts[OUTCOME_RETRIED],
        dead_lettered=counts[OUTCOME_DEAD_LETTERED],
        lease_lost=counts[OUTCOME_LEASE_LOST],
        released=counts[OUTCOME_RELEASED],
        timed_out=timed_out,
    )
