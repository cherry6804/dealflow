"""AI usage ledger and organization budgets (DFR1-017, hardened in WS6 WP1).

Units are explicit. A quantity is never interpreted as currency or tokens unless the
unit says so. Provider cost (``provider_cost_minor``) and customer credit consumption
(``customer_credits``) are separate units with separate budgets.

Lifecycle of billable work:
1. ``reserve``  creates a RESERVED entry, raises the reservation on the budget and sets an
                expiry (``RESERVATION_TTL``). It is refused when the budget is missing or lacks
                remaining quantity.
2. ``settle``   RESERVED -> RECORDED. Replaces the reservation with the actual quantity and frees
                the reserved quantity. Refused after the expiry instant.
   ``release``  RESERVED -> RELEASED. Frees the reservation when the work fails or is cancelled.
   ``expire_stale_reservations``  RESERVED -> RELEASED (reason ``expired``) for open reservations
                past their expiry. Run by the worker. Never touches a settled or released entry.
   ``record``   stores usage that was not reserved, for example usage reported later by a
                provider. It requires a configured budget and does not check remaining quantity.
3. ``reverse``  RECORDED -> REVERSED (for example a provider refund). Returns the quantity to the
                budget. The original row is kept.

Concurrency rules:
- Every state change locks the budget row first (``SELECT ... FOR UPDATE``), then the entry row.
  Every operation uses this order, so two operations on the same budget cannot deadlock.
- After each lock, the entry is read again with ``populate_existing``. A decision is never made on
  a state that another transaction may already have changed.
- Each budget counter change happens under the budget lock, so the counters stay exact.

Idempotency:
- Every entry is keyed by ``(organization_id, idempotency_key)``. A repeat with the same payload
  returns the existing entry and changes nothing. A repeat with a different payload raises
  ``IdempotencyConflictError``. Only the first matching payload is accepted.
- The payload is hashed into ``request_fingerprint``. Rows written before WP1 have no fingerprint
  and are returned unchanged.
- A concurrent duplicate insert that loses the race is handled in a savepoint and resolved against
  the winning row. No ``IntegrityError`` escapes for an ordinary duplicate.

Usage that exceeds the limit after settlement (for example output tokens above the reservation)
is recorded and reported as overrun; it is never silently discarded.

Functions flush and never commit. The caller owns the transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.db.models.ai_usage_event import (
    RELEASE_REASON_EXPIRED,
    RELEASE_REASON_RELEASED,
    AiUsageEvent,
)
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.governance.alert_thresholds import read_alert_thresholds
from app.outbox.service import enqueue_event

logger = logging.getLogger(__name__)

THRESHOLD_EVENT_TYPE = "ai.usage.threshold_reached"

# How long a reservation may stay open before the reaper releases it. A settlement after this
# instant is refused. This is a technical safety bound, not a commercial limit. Work that can run
# longer must settle within this window or be split. See docs/architecture/ai-usage-reservations.md.
RESERVATION_TTL = timedelta(minutes=15)
REAPER_BATCH_SIZE = 100

IDEMPOTENCY_CONSTRAINT = "uq_ai_usage_events_org_idempotency"


class UsageUnit(str, Enum):
    """Every metered unit. Quantities are integers in the unit named here."""

    TOKENS_INPUT = "tokens_input"
    TOKENS_OUTPUT = "tokens_output"
    AUDIO_MS = "audio_ms"
    IMAGES = "images"
    DOCUMENT_PAGES = "document_pages"
    PROVIDER_COST_MINOR = "provider_cost_minor"
    CUSTOMER_CREDITS = "customer_credits"


class UsageError(Exception):
    """Base class for usage ledger rule violations."""


class BudgetNotConfiguredError(UsageError):
    """Usage was refused because no budget exists for the unit and period (fail closed)."""


class BudgetExceededError(UsageError):
    """Billable work was refused because the reservation would exceed the budget."""

    def __init__(self, *, unit: str, requested: int, remaining: int) -> None:
        super().__init__(f"Budget for {unit} has {remaining} remaining, {requested} requested.")
        self.unit = unit
        self.requested = requested
        self.remaining = remaining


class InvalidUsageStateError(UsageError):
    """The entry is not in a state that allows the requested transition."""


class IdempotencyConflictError(UsageError):
    """The idempotency key was already used with a different payload."""


class ReservationExpiredError(UsageError):
    """The reservation expired and can no longer be settled."""


class SettlementConflictError(UsageError):
    """The entry was already settled with a different actual quantity."""


class UsageInvariantError(UsageError):
    """A budget counter would become inconsistent. The operation is refused, not repaired."""


@dataclass(frozen=True)
class BudgetPeriod:
    start: date
    end: date


@dataclass(frozen=True)
class ReservationReapResult:
    expired: int
    skipped: int


def budget_period_for(moment: datetime) -> BudgetPeriod:
    """Calendar month in UTC containing ``moment``. Boundaries are explicit and inclusive."""
    utc = moment.astimezone(UTC)
    start = date(utc.year, utc.month, 1)
    if utc.month == 12:
        next_start = date(utc.year + 1, 1, 1)
    else:
        next_start = date(utc.year, utc.month + 1, 1)
    end = date.fromordinal(next_start.toordinal() - 1)
    return BudgetPeriod(start=start, end=end)


def _validate_quantity(quantity: int) -> None:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("Usage quantity must be a positive integer.")


def _validate_actual(actual_quantity: int) -> None:
    if not isinstance(actual_quantity, int) or isinstance(actual_quantity, bool) or actual_quantity < 0:
        raise ValueError("Actual usage must be a non-negative integer.")


def _require_aware(moment: datetime, name: str) -> None:
    if moment.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")


def _unit_value(unit: UsageUnit | str) -> str:
    return UsageUnit(unit).value


def _database_now(db: Session) -> datetime:
    """The database clock. Every backend instance agrees on expiry, whatever its own clock says."""
    return db.scalar(select(func.now()))


def _fingerprint(kind: str, **fields: object) -> str:
    payload = {"kind": kind, **fields}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _used(budget: OrganizationUsageBudget) -> int:
    return budget.consumed_quantity + budget.reserved_quantity


def _budget_for(
    db: Session, *, organization_id: UUID, unit: str, moment: datetime
) -> OrganizationUsageBudget | None:
    """Return the budget for the period containing ``moment``, locked for this transaction."""
    period = budget_period_for(moment)
    return db.scalar(
        select(OrganizationUsageBudget)
        .where(
            OrganizationUsageBudget.organization_id == organization_id,
            OrganizationUsageBudget.unit == unit,
            OrganizationUsageBudget.period_start == period.start,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _lock_event(db: Session, event_id: UUID) -> AiUsageEvent | None:
    return db.scalar(
        select(AiUsageEvent)
        .where(AiUsageEvent.id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _existing(db: Session, *, organization_id: UUID, idempotency_key: str) -> AiUsageEvent | None:
    return db.scalar(
        select(AiUsageEvent).where(
            AiUsageEvent.organization_id == organization_id,
            AiUsageEvent.idempotency_key == idempotency_key,
        )
    )


def _same_request_or_conflict(event: AiUsageEvent, fingerprint: str) -> AiUsageEvent:
    """Return the stored entry for a repeat with the same payload. Raise for a different payload."""
    if event.request_fingerprint is not None and event.request_fingerprint != fingerprint:
        raise IdempotencyConflictError(
            "This idempotency key was already used for a different request."
        )
    return event


def _is_idempotency_violation(exc: IntegrityError) -> bool:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return constraint == IDEMPOTENCY_CONSTRAINT


def _insert_entry(
    db: Session,
    event: AiUsageEvent,
    *,
    organization_id: UUID,
    idempotency_key: str,
    fingerprint: str,
) -> tuple[AiUsageEvent, bool]:
    """Insert a new entry in a savepoint. Return (entry, created).

    A concurrent duplicate that wins the unique index is resolved against the stored row, so the
    caller sees the same result as a sequential repeat.
    """
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError as exc:
        if not _is_idempotency_violation(exc):
            raise
        stored = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
        if stored is None:
            raise
        return _same_request_or_conflict(stored, fingerprint), False
    return event, True


def _free_reservation(budget: OrganizationUsageBudget, event: AiUsageEvent) -> None:
    if budget.reserved_quantity < event.reserved_quantity:
        raise UsageInvariantError("Budget reserved quantity is lower than an open reservation.")
    budget.reserved_quantity -= event.reserved_quantity


def configure_budget(
    db: Session,
    *,
    organization_id: UUID,
    unit: UsageUnit | str,
    limit_quantity: int,
    moment: datetime,
) -> OrganizationUsageBudget:
    """Create or change the limit for the period containing ``moment``.

    Lowering a limit below what is already reserved or consumed is allowed. The budget
    then refuses all new billable work until the period ends.
    """
    unit_value = _unit_value(unit)
    if not isinstance(limit_quantity, int) or isinstance(limit_quantity, bool) or limit_quantity < 0:
        raise ValueError("Budget limit must be a non-negative integer.")
    period = budget_period_for(moment)
    budget = db.scalar(
        select(OrganizationUsageBudget)
        .where(
            OrganizationUsageBudget.organization_id == organization_id,
            OrganizationUsageBudget.unit == unit_value,
            OrganizationUsageBudget.period_start == period.start,
        )
        .with_for_update()
    )
    if budget is None:
        budget = OrganizationUsageBudget(
            organization_id=organization_id,
            unit=unit_value,
            period_start=period.start,
            period_end=period.end,
            limit_quantity=limit_quantity,
            reserved_quantity=0,
            consumed_quantity=0,
            last_alert_percent=0,
        )
        db.add(budget)
    else:
        budget.limit_quantity = limit_quantity
    db.flush()
    return budget


def highest_pending_threshold(
    thresholds: tuple[int, ...],
    *,
    limit: int,
    used: int,
    alerted: list[int],
) -> int | None:
    """Return the highest configured threshold that usage has reached and no delivered alert covers.

    State-based, not crossing-based. A threshold reached before the organization configured it, or
    reached while the alert was being queued, is still pending until its alert is delivered. The
    comparison ``used * 100 >= threshold * limit`` is exact for whole numbers. Only the highest pending
    threshold is returned, so one change that reaches several thresholds yields one alert.
    """
    if limit <= 0:
        return None
    pending = [t for t in thresholds if used * 100 >= t * limit and t not in alerted]
    return max(pending) if pending else None


def _announce_threshold(db: Session, *, budget: OrganizationUsageBudget) -> None:
    """Queue the alert for the highest pending threshold, if any.

    Delivery marks the threshold as covered (see ``deliver_usage_threshold_alert``). Until then the
    idempotency key ``usage-threshold:{budget}:{threshold}`` makes a repeat call return the queued event,
    so retries and concurrent usage queue at most one alert per threshold.
    """
    settings = read_alert_thresholds(db, organization_id=budget.organization_id)
    pending = highest_pending_threshold(
        settings.values,
        limit=budget.limit_quantity,
        used=_used(budget),
        alerted=list(budget.alerted_thresholds or []),
    )
    if pending is None:
        return
    enqueue_event(
        db,
        organization_id=budget.organization_id,
        event_type=THRESHOLD_EVENT_TYPE,
        aggregate_type="organization_usage_budget",
        aggregate_id=str(budget.id),
        idempotency_key=f"usage-threshold:{budget.id}:{pending}",
        payload={
            "unit": budget.unit,
            "threshold_percent": pending,
            "limit_quantity": budget.limit_quantity,
            "period_start": budget.period_start.isoformat(),
        },
    )


def announce_pending_threshold(db: Session, *, budget: OrganizationUsageBudget) -> None:
    """Public entry point for callers that change a budget or its thresholds."""
    _announce_threshold(db, budget=budget)


def reserve(
    db: Session,
    *,
    organization_id: UUID,
    unit: UsageUnit | str,
    quantity: int,
    idempotency_key: str,
    occurred_at: datetime,
    user_id: UUID | None = None,
    provider: str | None = None,
    model: str | None = None,
    task_type: str | None = None,
    agent_id: str | None = None,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    correlation_id: str | None = None,
    currency: str | None = None,
    now: datetime | None = None,
) -> AiUsageEvent:
    """Reserve quantity for billable work. Idempotent on ``idempotency_key``.

    ``now`` is injected by tests only. Production uses the database clock.
    """
    _validate_quantity(quantity)
    _require_aware(occurred_at, "occurred_at")
    unit_value = _unit_value(unit)
    fingerprint = _fingerprint(
        "reserve",
        unit=unit_value,
        quantity=quantity,
        occurred_at=occurred_at.isoformat(),
        provider=provider,
        model=model,
        task_type=task_type,
        user_id=str(user_id) if user_id else None,
        agent_id=agent_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        currency=currency,
    )

    budget = _budget_for(db, organization_id=organization_id, unit=unit_value, moment=occurred_at)
    if budget is None:
        raise BudgetNotConfiguredError(f"No {unit_value} budget is configured for this period.")

    existing = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if existing is not None:
        return _same_request_or_conflict(existing, fingerprint)

    remaining = budget.limit_quantity - _used(budget)
    if quantity > remaining:
        raise BudgetExceededError(unit=unit_value, requested=quantity, remaining=max(remaining, 0))

    moment = now if now is not None else _database_now(db)
    _require_aware(moment, "now")
    event = AiUsageEvent(
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        unit=unit_value,
        reserved_quantity=quantity,
        quantity=None,
        status=AiUsageEvent.STATUS_RESERVED,
        provider=provider,
        model=model,
        task_type=task_type,
        user_id=user_id,
        agent_id=agent_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        currency=currency,
        occurred_at=occurred_at,
        request_fingerprint=fingerprint,
        reservation_expires_at=moment + RESERVATION_TTL,
    )
    entry, created = _insert_entry(
        db,
        event,
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    if not created:
        return entry

    budget.reserved_quantity += quantity
    db.flush()
    _announce_threshold(db, budget=budget)
    db.flush()
    return entry


def settle(
    db: Session,
    *,
    organization_id: UUID,
    idempotency_key: str,
    actual_quantity: int,
    now: datetime | None = None,
) -> AiUsageEvent:
    """RESERVED -> RECORDED. Repeating with the same quantity returns the entry unchanged.

    Refused after the reservation expired, even when the reaper has not run yet, so a late
    settlement cannot race the reaper for the same reserved quantity.
    """
    _validate_actual(actual_quantity)
    candidate = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if candidate is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")

    budget = _budget_for(
        db, organization_id=organization_id, unit=candidate.unit, moment=candidate.occurred_at
    )
    if budget is None:
        raise BudgetNotConfiguredError("The budget for this usage entry no longer exists.")
    event = _lock_event(db, candidate.id)
    if event is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")

    if event.status == AiUsageEvent.STATUS_RECORDED:
        if event.quantity == actual_quantity:
            return event
        raise SettlementConflictError("This reservation was already settled with a different quantity.")
    if event.status == AiUsageEvent.STATUS_RELEASED and event.released_reason == RELEASE_REASON_EXPIRED:
        raise ReservationExpiredError("The reservation expired and cannot be settled.")
    _require_status(event, AiUsageEvent.STATUS_RESERVED)

    moment = now if now is not None else _database_now(db)
    _require_aware(moment, "now")
    if event.reservation_expires_at is None or event.reservation_expires_at <= moment:
        raise ReservationExpiredError("The reservation expired and cannot be settled.")

    _free_reservation(budget, event)
    budget.consumed_quantity += actual_quantity
    event.quantity = actual_quantity
    event.status = AiUsageEvent.STATUS_RECORDED
    db.flush()
    _announce_threshold(db, budget=budget)
    db.flush()
    return event


def release(
    db: Session,
    *,
    organization_id: UUID,
    idempotency_key: str,
) -> AiUsageEvent:
    """RESERVED -> RELEASED for work that failed or was cancelled. Repeating is a no-op.

    Allowed even after expiry while the reaper has not run. Releasing only frees budget.
    """
    candidate = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if candidate is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")

    budget = _budget_for(
        db, organization_id=organization_id, unit=candidate.unit, moment=candidate.occurred_at
    )
    if budget is None:
        raise BudgetNotConfiguredError("The budget for this usage entry no longer exists.")
    event = _lock_event(db, candidate.id)
    if event is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")

    if event.status == AiUsageEvent.STATUS_RELEASED:
        return event
    _require_status(event, AiUsageEvent.STATUS_RESERVED)

    _free_reservation(budget, event)
    event.status = AiUsageEvent.STATUS_RELEASED
    event.released_reason = RELEASE_REASON_RELEASED
    db.flush()
    return event


def expire_stale_reservations(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = REAPER_BATCH_SIZE,
) -> ReservationReapResult:
    """Release open reservations whose expiry has passed. The caller commits.

    Only RESERVED entries with ``reservation_expires_at <= now`` are changed. Settled, released and
    reversed entries and reservations still inside their window are never touched. Each candidate is
    processed under the same lock order as the other operations, and is re-checked after locking.
    Entries that cannot be locked right now, or whose budget is missing, are counted as skipped and
    left for a later pass.
    """
    if batch_size < 1:
        raise ValueError("Reaper batch size must be at least 1.")
    moment = now if now is not None else _database_now(db)
    _require_aware(moment, "now")

    candidates = db.execute(
        select(
            AiUsageEvent.id,
            AiUsageEvent.organization_id,
            AiUsageEvent.unit,
            AiUsageEvent.occurred_at,
        )
        .where(
            AiUsageEvent.status == AiUsageEvent.STATUS_RESERVED,
            AiUsageEvent.reservation_expires_at <= moment,
        )
        .order_by(AiUsageEvent.reservation_expires_at, AiUsageEvent.id)
        .limit(batch_size)
    ).all()

    expired = 0
    skipped = 0
    for event_id, organization_id, unit, occurred_at in candidates:
        budget = _budget_for(db, organization_id=organization_id, unit=unit, moment=occurred_at)
        if budget is None:
            logger.error(
                "reservation_reaper_budget_missing",
                extra={"usage_event_id": str(event_id), "organization_id": str(organization_id)},
            )
            skipped += 1
            continue

        event = db.scalar(
            select(AiUsageEvent)
            .where(AiUsageEvent.id == event_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if event is None:
            skipped += 1
            continue
        if (
            event.status != AiUsageEvent.STATUS_RESERVED
            or event.reservation_expires_at is None
            or event.reservation_expires_at > moment
        ):
            continue

        _free_reservation(budget, event)
        event.status = AiUsageEvent.STATUS_RELEASED
        event.released_reason = RELEASE_REASON_EXPIRED
        db.flush()
        expired += 1

    return ReservationReapResult(expired=expired, skipped=skipped)


def record(
    db: Session,
    *,
    organization_id: UUID,
    unit: UsageUnit | str,
    quantity: int,
    idempotency_key: str,
    occurred_at: datetime,
    provider: str | None = None,
    model: str | None = None,
    task_type: str | None = None,
    user_id: UUID | None = None,
    agent_id: str | None = None,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    correlation_id: str | None = None,
    currency: str | None = None,
) -> AiUsageEvent:
    """Store usage that was not reserved, for example delayed provider reporting.

    A budget must exist for the unit and period, otherwise the usage is refused and nothing is
    stored. The quantity is counted against the budget even if it exceeds the limit, and the
    budget then reports overrun through its remaining value. Idempotent on the key.
    """
    _validate_quantity(quantity)
    _require_aware(occurred_at, "occurred_at")
    unit_value = _unit_value(unit)
    fingerprint = _fingerprint(
        "record",
        unit=unit_value,
        quantity=quantity,
        occurred_at=occurred_at.isoformat(),
        provider=provider,
        model=model,
        task_type=task_type,
        user_id=str(user_id) if user_id else None,
        agent_id=agent_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        currency=currency,
    )

    budget = _budget_for(db, organization_id=organization_id, unit=unit_value, moment=occurred_at)
    if budget is None:
        raise BudgetNotConfiguredError(f"No {unit_value} budget is configured for this period.")

    existing = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if existing is not None:
        return _same_request_or_conflict(existing, fingerprint)

    event = AiUsageEvent(
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        unit=unit_value,
        reserved_quantity=quantity,
        quantity=quantity,
        status=AiUsageEvent.STATUS_RECORDED,
        provider=provider,
        model=model,
        task_type=task_type,
        user_id=user_id,
        agent_id=agent_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        currency=currency,
        occurred_at=occurred_at,
        request_fingerprint=fingerprint,
    )
    entry, created = _insert_entry(
        db,
        event,
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    if not created:
        return entry

    budget.consumed_quantity += quantity
    db.flush()
    _announce_threshold(db, budget=budget)
    db.flush()
    return entry


def reverse(db: Session, *, organization_id: UUID, idempotency_key: str) -> AiUsageEvent:
    """RECORDED -> REVERSED. Returns the quantity to the budget. Repeating is a no-op."""
    candidate = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if candidate is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")

    budget = _budget_for(
        db, organization_id=organization_id, unit=candidate.unit, moment=candidate.occurred_at
    )
    if budget is None:
        raise BudgetNotConfiguredError("The budget for this usage entry no longer exists.")
    event = _lock_event(db, candidate.id)
    if event is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")

    if event.status == AiUsageEvent.STATUS_REVERSED:
        return event
    _require_status(event, AiUsageEvent.STATUS_RECORDED)

    if event.quantity is None or budget.consumed_quantity < event.quantity:
        raise UsageInvariantError("Budget consumed quantity is lower than the entry being reversed.")
    budget.consumed_quantity -= event.quantity
    event.status = AiUsageEvent.STATUS_REVERSED
    db.flush()
    return event


def _require_status(event: AiUsageEvent, *allowed: str) -> None:
    if event.status not in allowed:
        raise InvalidUsageStateError(f"Usage entry is {event.status}; expected one of {allowed}.")


@dataclass(frozen=True)
class BudgetStatus:
    unit: str
    period_start: date
    period_end: date
    limit_quantity: int
    reserved_quantity: int
    consumed_quantity: int
    remaining_quantity: int
    utilization_percent: int
    overrun: bool


def budget_status(db: Session, *, organization_id: UUID, unit: UsageUnit | str, moment: datetime) -> BudgetStatus | None:
    """Return the budget for the period containing ``moment``, or None if not configured."""
    unit_value = _unit_value(unit)
    budget = db.scalar(
        select(OrganizationUsageBudget).where(
            OrganizationUsageBudget.organization_id == organization_id,
            OrganizationUsageBudget.unit == unit_value,
            OrganizationUsageBudget.period_start == budget_period_for(moment).start,
        )
    )
    if budget is None:
        return None
    used = _used(budget)
    remaining = budget.limit_quantity - used
    percent = used * 100 // budget.limit_quantity if budget.limit_quantity else 100
    return BudgetStatus(
        unit=unit_value,
        period_start=budget.period_start,
        period_end=budget.period_end,
        limit_quantity=budget.limit_quantity,
        reserved_quantity=budget.reserved_quantity,
        consumed_quantity=budget.consumed_quantity,
        remaining_quantity=remaining,
        utilization_percent=percent,
        overrun=remaining < 0,
    )


def change_budget(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    unit: UsageUnit | str,
    limit_quantity: int,
    moment: datetime,
) -> OrganizationUsageBudget:
    """Set a budget limit. Records a requested audit event first, then a completed one (WP3).

    The requested record is committed independently, before the limit changes. If it cannot be written,
    the change is not applied and ``AuditPersistenceError`` is raised.
    """
    from app.db.models.audit_event import AuditEvent

    unit_value = _unit_value(unit)
    period = budget_period_for(moment)
    previous = db.scalar(
        select(OrganizationUsageBudget.limit_quantity).where(
            OrganizationUsageBudget.organization_id == organization_id,
            OrganizationUsageBudget.unit == unit_value,
            OrganizationUsageBudget.period_start == period.start,
        )
    )
    requested = persist_independent_audit_event(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="governance",
        action="governance.budget.updated",
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key="governance.budgets.manage",
        resource_type="organization_usage_budget",
        resource_id=unit_value,
        metadata={
            "unit": unit_value,
            "period_start": period.start.isoformat(),
            "before": previous,
            "requested_after": limit_quantity,
        },
    )
    budget = configure_budget(
        db,
        organization_id=organization_id,
        unit=unit_value,
        limit_quantity=limit_quantity,
        moment=moment,
    )
    # A lower limit can put current usage over a threshold with no new usage. Evaluate it now (WP2).
    _announce_threshold(db, budget=budget)
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type="governance",
            action="governance.budget.updated",
            decision="allowed",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            correlation_id=requested.correlation_id,
            permission_key="governance.budgets.manage",
            resource_type="organization_usage_budget",
            resource_id=unit_value,
            event_metadata=json.dumps(
                {
                    "unit": unit_value,
                    "period_start": period.start.isoformat(),
                    "before": previous,
                    "after": limit_quantity,
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()
    return budget
