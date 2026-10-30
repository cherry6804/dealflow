"""AI usage ledger and budgets: idempotency, enforcement, lifecycle, alerts and races (DFR1-017)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal
from app.governance.usage_ledger import (
    THRESHOLD_EVENT_TYPE,
    BudgetExceededError,
    BudgetNotConfiguredError,
    InvalidUsageStateError,
    UsageUnit,
    budget_period_for,
    budget_status,
    configure_budget,
    record,
    release,
    reserve,
    reverse,
    settle,
)
from tests.test_team_api import create_manager

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def org() -> Iterator[UUID]:
    _, organization = create_manager(permissions=())
    yield organization.id
    with SessionLocal() as db:
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization.id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization.id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization.id))
        db.commit()


def _run(fn: Callable, *args, **kwargs):
    with SessionLocal() as db:
        # Keep loaded attributes readable after the session closes.
        db.expire_on_commit = False
        result = fn(db, *args, **kwargs)
        db.commit()
        return result


def _budget(organization_id: UUID, unit: UsageUnit, limit: int) -> None:
    _run(
        configure_budget,
        organization_id=organization_id,
        unit=unit,
        limit_quantity=limit,
        moment=NOW,
    )


def _reserve(organization_id: UUID, key: str, quantity: int, unit: UsageUnit = UsageUnit.TOKENS_OUTPUT):
    return _run(
        reserve,
        organization_id=organization_id,
        unit=unit,
        quantity=quantity,
        idempotency_key=key,
        occurred_at=NOW,
    )


def _status(organization_id: UUID, unit: UsageUnit = UsageUnit.TOKENS_OUTPUT):
    with SessionLocal() as db:
        return budget_status(db, organization_id=organization_id, unit=unit, moment=NOW)


def _event_count(organization_id: UUID, event_type: str = THRESHOLD_EVENT_TYPE) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == event_type,
            )
        )


def test_period_boundaries_are_calendar_months_in_utc() -> None:
    assert budget_period_for(datetime(2026, 1, 31, 23, 59, tzinfo=UTC)).end == date(2026, 1, 31)
    assert budget_period_for(datetime(2026, 2, 1, 0, 0, tzinfo=UTC)).start == date(2026, 2, 1)
    assert budget_period_for(datetime(2028, 2, 10, tzinfo=UTC)).end == date(2028, 2, 29)
    assert budget_period_for(datetime(2026, 12, 15, tzinfo=UTC)).end == date(2026, 12, 31)


def test_billable_work_is_refused_without_a_configured_budget(org) -> None:
    with pytest.raises(BudgetNotConfiguredError):
        _reserve(org, "no-budget-1", 10)

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AiUsageEvent).where(AiUsageEvent.organization_id == org)) == 0


def test_reservation_is_refused_when_it_would_exceed_the_limit(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    _reserve(org, "fit-1", 60)

    with pytest.raises(BudgetExceededError) as refused:
        _reserve(org, "too-big-1", 50)
    assert refused.value.remaining == 40

    _reserve(org, "fit-2", 40)
    status = _status(org)
    assert status.reserved_quantity == 100
    assert status.remaining_quantity == 0


def test_repeating_a_reservation_key_changes_nothing(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    first = _reserve(org, "same-key", 30)
    second = _reserve(org, "same-key", 30)

    assert first.id == second.id
    assert _status(org).reserved_quantity == 30


def test_settlement_replaces_the_reservation_with_actual_usage_once(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    _reserve(org, "settle-1", 60)

    _run(settle, organization_id=org, idempotency_key="settle-1", actual_quantity=25)
    _run(settle, organization_id=org, idempotency_key="settle-1", actual_quantity=25)

    status = _status(org)
    assert status.reserved_quantity == 0
    assert status.consumed_quantity == 25
    assert status.remaining_quantity == 75


def test_failed_work_releases_its_reservation(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    _reserve(org, "fail-1", 80)

    _run(release, organization_id=org, idempotency_key="fail-1")
    _run(release, organization_id=org, idempotency_key="fail-1")

    status = _status(org)
    assert status.reserved_quantity == 0
    assert status.remaining_quantity == 100
    with pytest.raises(InvalidUsageStateError):
        _run(settle, organization_id=org, idempotency_key="fail-1", actual_quantity=5)


def test_usage_recorded_after_the_fact_can_overrun_and_blocks_new_reservations(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)

    _run(
        record,
        organization_id=org,
        unit=UsageUnit.TOKENS_OUTPUT,
        quantity=130,
        idempotency_key="late-report-1",
        occurred_at=NOW,
    )

    status = _status(org)
    assert status.consumed_quantity == 130
    assert status.overrun is True
    assert status.remaining_quantity == -30
    with pytest.raises(BudgetExceededError):
        _reserve(org, "after-overrun-1", 1)


def test_reversal_returns_quantity_once_and_keeps_the_entry(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    _run(
        record,
        organization_id=org,
        unit=UsageUnit.TOKENS_OUTPUT,
        quantity=40,
        idempotency_key="refund-me-1",
        occurred_at=NOW,
    )

    _run(reverse, organization_id=org, idempotency_key="refund-me-1")
    _run(reverse, organization_id=org, idempotency_key="refund-me-1")

    status = _status(org)
    assert status.consumed_quantity == 0
    with SessionLocal() as db:
        entry = db.scalar(select(AiUsageEvent).where(AiUsageEvent.idempotency_key == "refund-me-1"))
        assert entry is not None
        assert entry.status == AiUsageEvent.STATUS_REVERSED
        assert entry.quantity == 40


def test_threshold_alerts_fire_once_at_70_85_and_100_percent(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)

    _reserve(org, "alert-a", 70)
    assert _event_count(org) == 1
    _reserve(org, "alert-b", 15)
    assert _event_count(org) == 2
    _reserve(org, "alert-c", 15)
    assert _event_count(org) == 3

    with SessionLocal() as db:
        payloads = sorted(
            row.payload["threshold_percent"]
            for row in db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.organization_id == org,
                    OutboxEvent.event_type == THRESHOLD_EVENT_TYPE,
                )
            ).all()
        )
    assert payloads == [70, 85, 100]


def test_units_are_budgeted_independently(org) -> None:
    _budget(org, UsageUnit.PROVIDER_COST_MINOR, 500)
    _budget(org, UsageUnit.CUSTOMER_CREDITS, 50)

    _reserve(org, "credits-1", 50, unit=UsageUnit.CUSTOMER_CREDITS)

    assert _status(org, UsageUnit.CUSTOMER_CREDITS).remaining_quantity == 0
    assert _status(org, UsageUnit.PROVIDER_COST_MINOR).remaining_quantity == 500


def test_usage_and_idempotency_are_scoped_to_one_organization(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    _reserve(org, "shared-key", 90)
    _, other = create_manager(permissions=())
    try:
        _budget(other.id, UsageUnit.TOKENS_OUTPUT, 100)
        entry = _reserve(other.id, "shared-key", 10)

        assert entry.organization_id == other.id
        assert _status(org).reserved_quantity == 90
        assert _status(other.id).reserved_quantity == 10
    finally:
        with SessionLocal() as db:
            db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == other.id))
            db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == other.id))
            db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == other.id))
            db.commit()


def test_concurrent_reservations_cannot_exceed_the_limit(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(key: str) -> None:
        barrier.wait()
        try:
            _reserve(org, key, 60)
            result = "reserved"
        except BudgetExceededError:
            result = "refused"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(f"race-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["refused", "reserved"]
    status = _status(org)
    assert status.reserved_quantity == 60
    assert status.remaining_quantity == 40


def test_a_delayed_provider_report_delivered_twice_is_counted_once(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    for _ in range(3):
        _run(
            record,
            organization_id=org,
            unit=UsageUnit.TOKENS_OUTPUT,
            quantity=25,
            idempotency_key="provider-report-42",
            occurred_at=NOW,
        )

    assert _status(org).consumed_quantity == 25


def test_settling_above_the_reservation_records_the_overrun_and_still_alerts(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)
    _reserve(org, "output-grew", 50)

    _run(settle, organization_id=org, idempotency_key="output-grew", actual_quantity=120)

    status = _status(org)
    assert status.consumed_quantity == 120
    assert status.reserved_quantity == 0
    assert status.overrun is True
    assert _event_count(org) == 1  # the 70% crossing from 50 -> 120 is announced once, at 100


def test_one_change_crossing_several_thresholds_announces_only_the_highest(org) -> None:
    _budget(org, UsageUnit.TOKENS_OUTPUT, 100)

    _reserve(org, "big-jump", 100)

    with SessionLocal() as db:
        payloads = [
            row.payload["threshold_percent"]
            for row in db.scalars(
                select(OutboxEvent).where(OutboxEvent.organization_id == org,
                                          OutboxEvent.event_type == THRESHOLD_EVENT_TYPE)
            ).all()
        ]
    assert payloads == [100]


def test_period_is_decided_in_utc_not_local_time() -> None:
    # 00:30 on 1 March in Kolkata (UTC+05:30) is still 28 February in UTC.
    kolkata = timezone(timedelta(hours=5, minutes=30))
    period = budget_period_for(datetime(2026, 3, 1, 0, 30, tzinfo=kolkata))

    assert period.start == date(2026, 2, 1)
    assert period.end == date(2026, 2, 28)


def test_cross_tenant_budget_reads_and_changes_are_refused() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.governance import router as governance_router
    from app.auth.dependencies import CurrentUserContext, get_current_user_context
    from app.db.session import get_db_session
    from tests.test_team_api import TestingSessionLocal

    reader, reader_org = create_manager(permissions=("governance.usage.read",))
    _, other_org = create_manager(permissions=())
    app = FastAPI()
    app.include_router(governance_router)

    def db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=reader)
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(other_org.id)})
            foreign_read = client.get("/api/v1/governance/usage/budgets")
            client.headers.update({"X-Organization-ID": str(reader_org.id)})
            # The reader has read access but not the budget-management permission.
            change = client.put(
                "/api/v1/governance/usage/budgets/tokens_output",
                json={"limit_quantity": 100, "confirm": True},
            )
            own_read = client.get("/api/v1/governance/usage/budgets")
    finally:
        with SessionLocal() as db:
            for organization in (reader_org, other_org):
                db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization.id))
            db.commit()

    assert foreign_read.status_code == 403
    assert change.status_code == 403
    assert own_read.status_code == 200
