"""AI usage ledger and organization budgets (DFR1-017).

Units are explicit. A quantity is never interpreted as currency or tokens unless the
unit says so. Provider cost (``provider_cost_minor``) and customer credit consumption
(``customer_credits``) are separate units with separate budgets.

Lifecycle of billable work:
1. ``reserve``  creates a reserved entry and raises the reservation on the budget.
                It is refused when the budget is missing or lacks remaining quantity.
2. ``settle``   replaces the reservation with the actual quantity used, and releases
                any unused reservation.
3. ``release``  frees the reservation when the work fails or is cancelled.
   ``record``   stores usage that was not reserved, for example usage reported later
                by a provider. It does not check remaining quantity.
4. ``reverse``  marks a recorded entry as reversed (for example a provider refund) and
                returns its quantity to the budget. The original row is kept.

Every operation is keyed by an idempotency key scoped to the organization. Repeating a
call returns the existing entry and changes nothing. Budget rows are locked with
``SELECT ... FOR UPDATE`` so concurrent reservations cannot exceed the limit.

Usage that exceeds the limit after settlement (for example output tokens above the
reservation) is recorded and reported as overrun; it is never silently discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.outbox.service import enqueue_event

THRESHOLDS: tuple[int, ...] = (70, 85, 100)
THRESHOLD_EVENT_TYPE = "ai.usage.threshold_reached"


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
    """Billable work was refused because no budget exists for the unit and period."""


class BudgetExceededError(UsageError):
    """Billable work was refused because the reservation would exceed the budget."""

    def __init__(self, *, unit: str, requested: int, remaining: int) -> None:
        super().__init__(f"Budget for {unit} has {remaining} remaining, {requested} requested.")
        self.unit = unit
        self.requested = requested
        self.remaining = remaining


class InvalidUsageStateError(UsageError):
    """The entry is not in a state that allows the requested transition."""


@dataclass(frozen=True)
class BudgetPeriod:
    start: date
    end: date


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


def _unit_value(unit: UsageUnit | str) -> str:
    return UsageUnit(unit).value


def _budget_for(
    db: Session, *, organization_id: UUID, unit: str, moment: datetime
) -> OrganizationUsageBudget | None:
    period = budget_period_for(moment)
    return db.scalar(
        select(OrganizationUsageBudget)
        .where(
            OrganizationUsageBudget.organization_id == organization_id,
            OrganizationUsageBudget.unit == unit,
            OrganizationUsageBudget.period_start == period.start,
        )
        .with_for_update()
    )


def _existing(db: Session, *, organization_id: UUID, idempotency_key: str) -> AiUsageEvent | None:
    return db.scalar(
        select(AiUsageEvent).where(
            AiUsageEvent.organization_id == organization_id,
            AiUsageEvent.idempotency_key == idempotency_key,
        )
    )


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


def _threshold_crossed(before: int, after: int, limit: int) -> int | None:
    """Return the highest threshold newly reached, or None. ``limit`` must be positive."""
    if limit <= 0:
        return None
    before_pct = before * 100 // limit
    after_pct = after * 100 // limit
    reached = [t for t in THRESHOLDS if before_pct < t <= after_pct]
    return max(reached) if reached else None


def _announce_threshold(
    db: Session,
    *,
    budget: OrganizationUsageBudget,
    before_used: int,
    after_used: int,
) -> None:
    crossed = _threshold_crossed(before_used, after_used, budget.limit_quantity)
    if crossed is None or crossed <= budget.last_alert_percent:
        return
    budget.last_alert_percent = crossed
    enqueue_event(
        db,
        organization_id=budget.organization_id,
        event_type=THRESHOLD_EVENT_TYPE,
        aggregate_type="organization_usage_budget",
        aggregate_id=str(budget.id),
        idempotency_key=f"usage-threshold:{budget.id}:{crossed}",
        payload={
            "unit": budget.unit,
            "threshold_percent": crossed,
            "limit_quantity": budget.limit_quantity,
            "period_start": budget.period_start.isoformat(),
        },
    )


def _used(budget: OrganizationUsageBudget) -> int:
    return budget.consumed_quantity + budget.reserved_quantity


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
) -> AiUsageEvent:
    """Reserve quantity for billable work. Idempotent on ``idempotency_key``."""
    _validate_quantity(quantity)
    unit_value = _unit_value(unit)

    existing = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if existing is not None:
        return existing

    budget = _budget_for(db, organization_id=organization_id, unit=unit_value, moment=occurred_at)
    if budget is None:
        raise BudgetNotConfiguredError(f"No {unit_value} budget is configured for this period.")

    remaining = budget.limit_quantity - _used(budget)
    if quantity > remaining:
        raise BudgetExceededError(unit=unit_value, requested=quantity, remaining=max(remaining, 0))

    before = _used(budget)
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
    )
    db.add(event)
    budget.reserved_quantity += quantity
    db.flush()
    _announce_threshold(db, budget=budget, before_used=before, after_used=_used(budget))
    db.flush()
    return event


def _require_status(event: AiUsageEvent, *allowed: str) -> None:
    if event.status not in allowed:
        raise InvalidUsageStateError(f"Usage entry is {event.status}; expected one of {allowed}.")


def _budget_of(db: Session, event: AiUsageEvent) -> OrganizationUsageBudget | None:
    return _budget_for(db, organization_id=event.organization_id, unit=event.unit, moment=event.occurred_at)


def settle(
    db: Session,
    *,
    organization_id: UUID,
    idempotency_key: str,
    actual_quantity: int,
) -> AiUsageEvent:
    """Replace a reservation with the actual usage. Repeating the call is a no-op."""
    if not isinstance(actual_quantity, int) or isinstance(actual_quantity, bool) or actual_quantity < 0:
        raise ValueError("Actual usage must be a non-negative integer.")
    event = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if event is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")
    if event.status == AiUsageEvent.STATUS_RECORDED:
        return event
    _require_status(event, AiUsageEvent.STATUS_RESERVED)

    budget = _budget_of(db, event)
    if budget is None:
        raise BudgetNotConfiguredError("The budget for this usage entry no longer exists.")
    before = _used(budget)
    budget.reserved_quantity -= event.reserved_quantity
    budget.consumed_quantity += actual_quantity
    event.quantity = actual_quantity
    event.status = AiUsageEvent.STATUS_RECORDED
    db.flush()
    _announce_threshold(db, budget=budget, before_used=before, after_used=_used(budget))
    db.flush()
    return event


def release(db: Session, *, organization_id: UUID, idempotency_key: str) -> AiUsageEvent:
    """Free a reservation for work that failed or was cancelled. Repeating is a no-op."""
    event = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if event is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")
    if event.status == AiUsageEvent.STATUS_RELEASED:
        return event
    _require_status(event, AiUsageEvent.STATUS_RESERVED)

    budget = _budget_of(db, event)
    if budget is not None:
        budget.reserved_quantity -= event.reserved_quantity
    event.status = AiUsageEvent.STATUS_RELEASED
    db.flush()
    return event


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

    The quantity is counted against the budget even if it exceeds the limit, and the
    budget then reports overrun through its remaining value. Idempotent on the key.
    """
    _validate_quantity(quantity)
    unit_value = _unit_value(unit)

    existing = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if existing is not None:
        return existing

    budget = _budget_for(db, organization_id=organization_id, unit=unit_value, moment=occurred_at)
    before = _used(budget) if budget is not None else 0
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
    )
    db.add(event)
    if budget is not None:
        budget.consumed_quantity += quantity
        db.flush()
        _announce_threshold(db, budget=budget, before_used=before, after_used=_used(budget))
    db.flush()
    return event


def reverse(db: Session, *, organization_id: UUID, idempotency_key: str) -> AiUsageEvent:
    """Mark a recorded entry as reversed and return its quantity. Repeating is a no-op."""
    event = _existing(db, organization_id=organization_id, idempotency_key=idempotency_key)
    if event is None:
        raise InvalidUsageStateError("No usage entry exists for this key.")
    if event.status == AiUsageEvent.STATUS_REVERSED:
        return event
    _require_status(event, AiUsageEvent.STATUS_RECORDED)

    budget = _budget_of(db, event)
    if budget is not None and event.quantity is not None:
        budget.consumed_quantity -= event.quantity
    event.status = AiUsageEvent.STATUS_REVERSED
    db.flush()
    return event


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
    """Set a budget limit and write an audit event with the before and after values."""
    import json

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
    budget = configure_budget(
        db,
        organization_id=organization_id,
        unit=unit_value,
        limit_quantity=limit_quantity,
        moment=moment,
    )
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type="governance",
            action="governance.budget.updated",
            decision="allowed",
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
