"""AI usage ledger hardening: reservation expiry, reaper, idempotency and concurrency (WS6 WP1).

These tests run on PostgreSQL. Concurrency cases use real threads with their own committed
sessions, so the database locks and unique constraints are exercised, not simulated.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from app.db.models.ai_pricing import AiProviderCostEntry
from app.db.models.ai_usage_event import (
    RELEASE_REASON_EXPIRED,
    RELEASE_REASON_RELEASED,
    AiUsageEvent,
)
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal
from app.governance.usage_ledger import (
    RESERVATION_TTL,
    BudgetExceededError,
    BudgetNotConfiguredError,
    IdempotencyConflictError,
    InvalidUsageStateError,
    ReservationExpiredError,
    ReservationReapResult,
    SettlementConflictError,
    UsageError,
    UsageUnit,
    configure_budget,
    expire_stale_reservations,
    record,
    release,
    reserve,
    reverse,
    settle,
)
from tests.test_team_api import create_manager

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
EXPIRY = NOW + RESERVATION_TTL
AFTER_EXPIRY = EXPIRY + timedelta(seconds=1)
UNIT = UsageUnit.TOKENS_OUTPUT


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
        db.execute(delete(AiProviderCostEntry).where(AiProviderCostEntry.organization_id == organization_id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization_id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        db.commit()


@pytest.fixture
def org() -> Iterator[UUID]:
    _, organization = create_manager(permissions=())
    yield organization.id
    _cleanup(organization.id)


@pytest.fixture
def other_org() -> Iterator[UUID]:
    _, organization = create_manager(permissions=())
    yield organization.id
    _cleanup(organization.id)


def _run(fn: Callable, *args, **kwargs):
    """Run one operation in its own transaction and commit it."""
    with SessionLocal() as db:
        db.expire_on_commit = False
        result = fn(db, *args, **kwargs)
        db.commit()
        return result


def _budget(organization_id: UUID, limit: int, unit: UsageUnit = UNIT) -> None:
    _run(configure_budget, organization_id=organization_id, unit=unit, limit_quantity=limit, moment=NOW)


def _reserve(organization_id: UUID, key: str, quantity: int, *, unit: UsageUnit = UNIT, now: datetime = NOW):
    return _run(
        reserve,
        organization_id=organization_id,
        unit=unit,
        quantity=quantity,
        idempotency_key=key,
        occurred_at=NOW,
        now=now,
    )


def _settle(organization_id: UUID, key: str, actual: int, *, now: datetime = NOW):
    return _run(settle, organization_id=organization_id, idempotency_key=key, actual_quantity=actual, now=now)


def _release(organization_id: UUID, key: str):
    return _run(release, organization_id=organization_id, idempotency_key=key)


def _reap(now: datetime, batch_size: int = 100) -> ReservationReapResult:
    return _run(expire_stale_reservations, now=now, batch_size=batch_size)


def _entry(organization_id: UUID, key: str) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(
            select(AiUsageEvent).where(
                AiUsageEvent.organization_id == organization_id,
                AiUsageEvent.idempotency_key == key,
            )
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "status": row.status,
            "quantity": row.quantity,
            "reserved_quantity": row.reserved_quantity,
            "released_reason": row.released_reason,
            "expires_at": row.reservation_expires_at,
            "fingerprint": row.request_fingerprint,
        }


def _entry_count(organization_id: UUID) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(AiUsageEvent.id).where(AiUsageEvent.organization_id == organization_id)).all())


def _counters(organization_id: UUID, unit: UsageUnit = UNIT) -> tuple[int, int]:
    """Return (reserved, consumed) for the budget of the period containing NOW."""
    with SessionLocal() as db:
        budget = db.scalar(
            select(OrganizationUsageBudget).where(
                OrganizationUsageBudget.organization_id == organization_id,
                OrganizationUsageBudget.unit == unit.value,
            )
        )
        return budget.reserved_quantity, budget.consumed_quantity


def _race(functions: list[Callable]) -> tuple[list, list]:
    """Run each callable in its own thread, released together, and collect results and errors."""
    barrier = threading.Barrier(len(functions))
    results: list = [None] * len(functions)
    errors: list = [None] * len(functions)

    def run(index: int, fn: Callable) -> None:
        barrier.wait()
        try:
            results[index] = fn()
        except UsageError as exc:  # expected rule violations are collected and asserted by the test
            errors[index] = exc

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(functions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a race thread did not finish"
    return results, errors


# --- Reservation creation and expiry -------------------------------------------------------------


def test_reservation_records_its_expiry_and_request_fingerprint(org) -> None:
    _budget(org, 100)
    entry = _reserve(org, "create-1", 40)

    stored = _entry(org, "create-1")
    assert stored["status"] == AiUsageEvent.STATUS_RESERVED
    assert stored["expires_at"] == EXPIRY
    assert stored["fingerprint"] is not None
    assert _counters(org) == (40, 0)
    assert entry.status == AiUsageEvent.STATUS_RESERVED


def test_an_open_reservation_is_protected_before_its_expiry(org) -> None:
    _budget(org, 100)
    _reserve(org, "active-1", 40)

    result = _reap(EXPIRY - timedelta(seconds=1))

    assert result == ReservationReapResult(expired=0, skipped=0)
    assert _entry(org, "active-1")["status"] == AiUsageEvent.STATUS_RESERVED
    assert _counters(org) == (40, 0)


def test_the_reaper_releases_an_expired_reservation_and_frees_its_budget(org) -> None:
    _budget(org, 100)
    _reserve(org, "expire-1", 40)

    result = _reap(EXPIRY)

    assert result.expired == 1
    stored = _entry(org, "expire-1")
    assert stored["status"] == AiUsageEvent.STATUS_RELEASED
    assert stored["released_reason"] == RELEASE_REASON_EXPIRED
    assert _counters(org) == (0, 0)


def test_expired_capacity_can_be_reserved_again_after_the_reaper_runs(org) -> None:
    _budget(org, 100)
    _reserve(org, "fill-1", 100)
    with pytest.raises(BudgetExceededError):
        _reserve(org, "blocked-1", 1)

    _reap(EXPIRY)

    _reserve(org, "fill-2", 100)
    assert _counters(org) == (100, 0)


def test_the_reaper_leaves_settled_released_and_open_entries_alone(org) -> None:
    _budget(org, 1000)
    _reserve(org, "settled-1", 10, now=NOW)
    _settle(org, "settled-1", 7, now=NOW + timedelta(minutes=1))
    _reserve(org, "released-1", 20, now=NOW)
    _release(org, "released-1")
    _reserve(org, "expired-1", 30, now=NOW)

    result = _reap(EXPIRY)

    assert result.expired == 1
    assert _entry(org, "settled-1")["status"] == AiUsageEvent.STATUS_RECORDED
    assert _entry(org, "released-1")["released_reason"] == RELEASE_REASON_RELEASED
    assert _entry(org, "expired-1")["released_reason"] == RELEASE_REASON_EXPIRED
    assert _counters(org) == (0, 7)


def test_reaper_runs_are_idempotent(org) -> None:
    _budget(org, 100)
    _reserve(org, "again-1", 25)

    assert _reap(EXPIRY).expired == 1
    assert _reap(EXPIRY).expired == 0
    assert _counters(org) == (0, 0)


def test_the_reaper_processes_at_most_one_batch_per_run(org) -> None:
    _budget(org, 1000)
    for index in range(5):
        _reserve(org, f"batch-{index}", 10)

    assert _reap(EXPIRY, batch_size=2).expired == 2
    assert _reap(EXPIRY, batch_size=2).expired == 2
    assert _reap(EXPIRY, batch_size=2).expired == 1
    assert _counters(org) == (0, 0)


def test_the_reaper_rejects_a_non_positive_batch(org) -> None:
    with SessionLocal() as db, pytest.raises(ValueError):
        expire_stale_reservations(db, now=EXPIRY, batch_size=0)


def test_a_reservation_in_use_by_another_transaction_is_skipped_not_released(org) -> None:
    _budget(org, 100)
    _reserve(org, "locked-1", 40)
    held_id = _entry(org, "locked-1")["id"]

    holder = SessionLocal()
    try:
        holder.execute(select(AiUsageEvent.id).where(AiUsageEvent.id == held_id).with_for_update())
        with SessionLocal() as reaper_db:
            result = expire_stale_reservations(reaper_db, now=EXPIRY)
            reaper_db.commit()
        assert result == ReservationReapResult(expired=0, skipped=1)
        assert _entry(org, "locked-1")["status"] == AiUsageEvent.STATUS_RESERVED
    finally:
        holder.rollback()
        holder.close()

    assert _reap(EXPIRY).expired == 1


# --- Settlement, release and reversal ------------------------------------------------------------


def test_settlement_before_expiry_records_actual_usage_and_frees_the_rest(org) -> None:
    _budget(org, 100)
    _reserve(org, "before-1", 60)

    settled = _settle(org, "before-1", 25, now=EXPIRY - timedelta(minutes=1))

    assert settled.status == AiUsageEvent.STATUS_RECORDED
    assert _counters(org) == (0, 25)


def test_settlement_after_expiry_is_refused_even_before_the_reaper_runs(org) -> None:
    _budget(org, 100)
    _reserve(org, "late-1", 60)

    with pytest.raises(ReservationExpiredError):
        _settle(org, "late-1", 25, now=AFTER_EXPIRY)

    assert _entry(org, "late-1")["status"] == AiUsageEvent.STATUS_RESERVED
    assert _counters(org) == (60, 0)


def test_settlement_after_the_reaper_ran_is_refused(org) -> None:
    _budget(org, 100)
    _reserve(org, "reaped-1", 60)
    _reap(EXPIRY)

    with pytest.raises(ReservationExpiredError):
        _settle(org, "reaped-1", 25, now=EXPIRY - timedelta(minutes=1))

    assert _counters(org) == (0, 0)


def test_duplicate_settlement_with_the_same_quantity_changes_nothing(org) -> None:
    _budget(org, 100)
    _reserve(org, "dup-settle-1", 60)
    _settle(org, "dup-settle-1", 25)

    again = _settle(org, "dup-settle-1", 25)

    assert again.status == AiUsageEvent.STATUS_RECORDED
    assert _counters(org) == (0, 25)


def test_duplicate_settlement_with_a_different_quantity_is_a_conflict(org) -> None:
    _budget(org, 100)
    _reserve(org, "dup-settle-2", 60)
    _settle(org, "dup-settle-2", 25)

    with pytest.raises(SettlementConflictError):
        _settle(org, "dup-settle-2", 30)

    assert _counters(org) == (0, 25)


def test_duplicate_release_changes_nothing(org) -> None:
    _budget(org, 100)
    _reserve(org, "dup-release-1", 60)
    _release(org, "dup-release-1")

    again = _release(org, "dup-release-1")

    assert again.status == AiUsageEvent.STATUS_RELEASED
    assert _counters(org) == (0, 0)


def test_release_after_settlement_is_refused(org) -> None:
    _budget(org, 100)
    _reserve(org, "release-settled-1", 60)
    _settle(org, "release-settled-1", 25)

    with pytest.raises(InvalidUsageStateError):
        _release(org, "release-settled-1")

    assert _counters(org) == (0, 25)


def test_reverse_returns_the_quantity_once_and_keeps_the_entry(org) -> None:
    _budget(org, 100)
    _run(record, organization_id=org, unit=UNIT, quantity=30, idempotency_key="rev-1", occurred_at=NOW)

    _run(reverse, organization_id=org, idempotency_key="rev-1")
    _run(reverse, organization_id=org, idempotency_key="rev-1")

    stored = _entry(org, "rev-1")
    assert stored["status"] == AiUsageEvent.STATUS_REVERSED
    assert stored["quantity"] == 30
    assert _counters(org) == (0, 0)


def test_reverse_refuses_an_open_reservation(org) -> None:
    _budget(org, 100)
    _reserve(org, "rev-open-1", 30)

    with pytest.raises(InvalidUsageStateError):
        _run(reverse, organization_id=org, idempotency_key="rev-open-1")

    assert _counters(org) == (30, 0)


# --- Idempotency and concurrency -----------------------------------------------------------------


def test_repeating_a_reservation_with_the_same_payload_returns_the_same_entry(org) -> None:
    _budget(org, 100)
    first = _reserve(org, "same-1", 30)
    second = _reserve(org, "same-1", 30)

    assert first.id == second.id
    assert _counters(org) == (30, 0)


def test_repeating_a_key_with_a_different_quantity_is_a_clear_conflict(org) -> None:
    _budget(org, 100)
    _reserve(org, "conflict-1", 30)

    with pytest.raises(IdempotencyConflictError):
        _reserve(org, "conflict-1", 31)

    assert _entry_count(org) == 1
    assert _counters(org) == (30, 0)


def test_reusing_a_key_for_another_unit_is_a_conflict(org) -> None:
    _budget(org, 100)
    _budget(org, 100, unit=UsageUnit.AUDIO_MS)
    _reserve(org, "unit-conflict-1", 30)

    with pytest.raises(IdempotencyConflictError):
        _reserve(org, "unit-conflict-1", 30, unit=UsageUnit.AUDIO_MS)

    assert _counters(org, UNIT) == (30, 0)
    assert _counters(org, UsageUnit.AUDIO_MS) == (0, 0)


def test_concurrent_identical_reservations_produce_one_logical_reservation(org) -> None:
    _budget(org, 100)

    results, errors = _race([lambda: _reserve(org, "race-same-1", 30) for _ in range(4)])

    assert errors == [None] * 4
    ids = {entry.id for entry in results}
    assert len(ids) == 1
    assert _entry_count(org) == 1
    assert _counters(org) == (30, 0)


def test_concurrent_conflicting_payloads_yield_one_reservation_and_one_conflict(org) -> None:
    _budget(org, 100)

    results, errors = _race(
        [lambda: _reserve(org, "race-conflict-1", 30), lambda: _reserve(org, "race-conflict-1", 40)]
    )

    successes = [entry for entry in results if entry is not None]
    conflicts = [error for error in errors if error is not None]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], IdempotencyConflictError)
    assert _entry_count(org) == 1
    assert _counters(org) == (successes[0].reserved_quantity, 0)


def test_concurrent_reaper_runs_release_each_reservation_exactly_once(org) -> None:
    _budget(org, 1000)
    for index in range(5):
        _reserve(org, f"reap-race-{index}", 10)

    results, errors = _race([lambda: _reap(EXPIRY) for _ in range(3)])

    assert errors == [None] * 3
    assert sum(result.expired for result in results) == 5
    assert _counters(org) == (0, 0)


def test_concurrent_settlement_and_reaper_never_double_count(org) -> None:
    _budget(org, 1000)
    _reserve(org, "settle-vs-reap-1", 50, now=NOW)

    results, errors = _race(
        [
            lambda: _settle(org, "settle-vs-reap-1", 20, now=EXPIRY - timedelta(minutes=1)),
            lambda: _reap(EXPIRY),
        ]
    )

    stored = _entry(org, "settle-vs-reap-1")
    reserved, consumed = _counters(org)
    assert reserved == 0
    if stored["status"] == AiUsageEvent.STATUS_RECORDED:
        assert consumed == 20
        assert results[1].expired == 0
        assert errors[0] is None
    else:
        assert stored["status"] == AiUsageEvent.STATUS_RELEASED
        assert consumed == 0
        assert results[1].expired == 1
        assert isinstance(errors[0], ReservationExpiredError)


# --- Budget enforcement and missing budgets ------------------------------------------------------


def test_a_missing_budget_refuses_a_reservation_and_stores_nothing(org) -> None:
    with pytest.raises(BudgetNotConfiguredError):
        _reserve(org, "no-budget-r-1", 10)

    assert _entry_count(org) == 0


def test_a_missing_budget_refuses_a_direct_record_and_stores_nothing(org) -> None:
    with pytest.raises(BudgetNotConfiguredError):
        _run(record, organization_id=org, unit=UNIT, quantity=10, idempotency_key="no-budget-rec-1", occurred_at=NOW)

    assert _entry_count(org) == 0


def test_a_rolled_back_reservation_leaves_no_entry_and_no_budget_change(org) -> None:
    _budget(org, 100)
    with SessionLocal() as db:
        reserve(
            db, organization_id=org, unit=UNIT, quantity=30, idempotency_key="rollback-1",
            occurred_at=NOW, now=NOW,
        )
        db.rollback()

    assert _entry_count(org) == 0
    assert _counters(org) == (0, 0)


def test_a_refused_reservation_changes_nothing_when_the_caller_rolls_back(org) -> None:
    _budget(org, 100)
    with SessionLocal() as db:
        with pytest.raises(BudgetExceededError):
            reserve(
                db, organization_id=org, unit=UNIT, quantity=101, idempotency_key="refused-1",
                occurred_at=NOW, now=NOW,
            )
        db.rollback()

    assert _entry_count(org) == 0
    assert _counters(org) == (0, 0)


def test_provider_cost_and_customer_credits_keep_separate_budgets(org) -> None:
    _budget(org, 100, unit=UsageUnit.PROVIDER_COST_MINOR)
    _budget(org, 100, unit=UsageUnit.CUSTOMER_CREDITS)
    _reserve(org, "cost-1", 50, unit=UsageUnit.PROVIDER_COST_MINOR)
    _reserve(org, "credit-1", 60, unit=UsageUnit.CUSTOMER_CREDITS)

    _reap(EXPIRY)

    assert _counters(org, UsageUnit.PROVIDER_COST_MINOR) == (0, 0)
    assert _counters(org, UsageUnit.CUSTOMER_CREDITS) == (0, 0)


# --- Tenant isolation ----------------------------------------------------------------------------


def test_the_reaper_releases_other_tenants_expired_reservations_without_touching_this_tenant(org, other_org) -> None:
    _budget(org, 100)
    _budget(other_org, 100)
    _reserve(org, "tenant-a-1", 40, now=NOW + timedelta(hours=1))
    _reserve(other_org, "tenant-b-1", 40, now=NOW)

    _reap(EXPIRY)

    assert _entry(other_org, "tenant-b-1")["released_reason"] == RELEASE_REASON_EXPIRED
    assert _entry(org, "tenant-a-1")["status"] == AiUsageEvent.STATUS_RESERVED
    assert _counters(other_org) == (0, 0)
    assert _counters(org) == (40, 0)


def test_one_tenant_cannot_settle_or_release_another_tenants_reservation(org, other_org) -> None:
    _budget(org, 100)
    _budget(other_org, 100)
    _reserve(other_org, "foreign-1", 40)

    with pytest.raises(InvalidUsageStateError):
        _settle(org, "foreign-1", 10)
    with pytest.raises(InvalidUsageStateError):
        _release(org, "foreign-1")

    assert _entry(other_org, "foreign-1")["status"] == AiUsageEvent.STATUS_RESERVED
    assert _counters(other_org) == (40, 0)


# --- Historical data and outbox delivery ---------------------------------------------------------


def test_a_pre_wp1_reservation_without_a_fingerprint_is_returned_unchanged(org) -> None:
    _budget(org, 100)
    legacy_id = _legacy_row(org, "legacy-1", status=AiUsageEvent.STATUS_RESERVED, quantity=40)

    entry = _reserve(org, "legacy-1", 99)

    assert entry.id == legacy_id
    assert entry.request_fingerprint is None


def _legacy_row(organization_id: UUID, key: str, *, status: str, quantity: int) -> UUID:
    row = AiUsageEvent(
        organization_id=organization_id,
        idempotency_key=key,
        unit=UNIT.value,
        reserved_quantity=quantity,
        quantity=quantity if status != AiUsageEvent.STATUS_RESERVED else None,
        status=status,
        occurred_at=NOW,
        reservation_expires_at=EXPIRY if status == AiUsageEvent.STATUS_RESERVED else None,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        return row.id


def test_a_threshold_crossed_by_a_repeated_request_is_announced_once(org) -> None:
    _budget(org, 100)
    for _ in range(3):
        _reserve(org, "threshold-repeat-1", 80)

    with SessionLocal() as db:
        count = len(
            db.scalars(
                select(OutboxEvent.id).where(
                    OutboxEvent.organization_id == org,
                    OutboxEvent.event_type == "ai.usage.threshold_reached",
                )
            ).all()
        )
    assert count == 1
