"""DFR1-017: idempotency conflicts, reservation expiry, thresholds, breakdowns and gate integration.

Extends ``test_usage_ledger.py``, which covers the basic lifecycle. Every case runs against PostgreSQL.
Each test creates its own organization, so nothing is shared between tests.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal
from app.governance import usage_maintenance
from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES, AUTOMATION_MASTER
from app.governance.execution_gate import (
    BudgetReservation,
    ExecutionRequest,
    authorize_execution,
)
from app.governance.service import set_capability_enabled
from app.governance.usage_ledger import (
    THRESHOLD_EVENT_TYPE,
    BudgetExceededError,
    IdempotencyConflictError,
    InvalidUsageStateError,
    UsageUnit,
    budget_status,
    configure_budget,
    record,
    release,
    release_expired,
    reserve,
    settle,
    usage_breakdown,
)
from tests.governance_helpers import attested_user_context
from tests.test_team_api import create_manager

NOW = datetime.now(UTC)
UNIT = UsageUnit.TOKENS_OUTPUT


@pytest.fixture
def org() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(permissions=())
    yield organization.id, user.id
    with SessionLocal() as db:
        for model in (AiUsageEvent, OrganizationUsageBudget, OutboxEvent, AuditEvent, OrganizationCapabilitySetting):
            db.execute(delete(model).where(model.organization_id == organization.id))
        db.commit()


def _budget(organization_id: UUID, limit: int, *, unit: UsageUnit = UNIT, warning=None, critical=None) -> None:
    with SessionLocal() as db:
        configure_budget(
            db,
            organization_id=organization_id,
            unit=unit,
            limit_quantity=limit,
            moment=NOW,
            warning_percent=warning,
            critical_percent=critical,
        )
        db.commit()


def _reserve(organization_id: UUID, key: str, quantity: int, *, unit: UsageUnit = UNIT, capability=None) -> UUID:
    with SessionLocal() as db:
        event = reserve(
            db,
            organization_id=organization_id,
            unit=unit,
            quantity=quantity,
            idempotency_key=key,
            occurred_at=NOW,
            capability_key=capability,
        )
        db.commit()
        return event.id


def _budget_row(organization_id: UUID) -> OrganizationUsageBudget:
    with SessionLocal() as db:
        row = db.scalar(
            select(OrganizationUsageBudget).where(
                OrganizationUsageBudget.organization_id == organization_id,
                OrganizationUsageBudget.unit == UNIT.value,
            )
        )
        assert row is not None
        db.expunge(row)
        return row


def _threshold_events(organization_id: UUID) -> list[int]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == THRESHOLD_EVENT_TYPE,
            )
        ).all()
        return sorted(row.payload["threshold_percent"] for row in rows)


# --- Idempotency: duplicates and conflicts -----------------------------------------------------


def test_a_repeated_reservation_with_the_same_quantity_returns_the_same_entry(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)

    first = _reserve(organization_id, "req-1", 10)
    second = _reserve(organization_id, "req-1", 10)

    assert first == second
    assert _budget_row(organization_id).reserved_quantity == 10


def test_a_conflicting_reservation_quantity_is_refused_and_changes_nothing(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _reserve(organization_id, "req-2", 10)

    with SessionLocal() as db:
        with pytest.raises(IdempotencyConflictError):
            reserve(
                db,
                organization_id=organization_id,
                unit=UNIT,
                quantity=50,
                idempotency_key="req-2",
                occurred_at=NOW,
            )
        db.rollback()
    assert _budget_row(organization_id).reserved_quantity == 10


def test_a_conflicting_unit_for_the_same_key_is_refused(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _budget(organization_id, 100, unit=UsageUnit.IMAGES)
    _reserve(organization_id, "req-3", 10)

    with SessionLocal() as db:
        with pytest.raises(IdempotencyConflictError):
            reserve(
                db,
                organization_id=organization_id,
                unit=UsageUnit.IMAGES,
                quantity=10,
                idempotency_key="req-3",
                occurred_at=NOW,
            )
        db.rollback()


def test_a_conflicting_recording_for_an_existing_key_is_refused(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    with SessionLocal() as db:
        record(
            db,
            organization_id=organization_id,
            unit=UNIT,
            quantity=7,
            idempotency_key="delayed-1",
            occurred_at=NOW,
        )
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(IdempotencyConflictError):
            record(
                db,
                organization_id=organization_id,
                unit=UNIT,
                quantity=9,
                idempotency_key="delayed-1",
                occurred_at=NOW,
            )
        db.rollback()
    assert _budget_row(organization_id).consumed_quantity == 7


def test_two_simultaneous_first_requests_with_one_key_create_one_entry(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 1000)
    barrier = threading.Barrier(2)
    results: list[UUID] = []
    errors: list[BaseException] = []

    def attempt() -> None:
        try:
            barrier.wait()
            results.append(_reserve(organization_id, "race-key", 10))
        except BaseException as error:  # noqa: BLE001 - surfaced by the assertion below.
            errors.append(error)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(set(results)) == 1
    with SessionLocal() as db:
        count = len(
            db.scalars(
                select(AiUsageEvent.id).where(
                    AiUsageEvent.organization_id == organization_id,
                    AiUsageEvent.idempotency_key == "race-key",
                )
            ).all()
        )
    assert count == 1
    assert _budget_row(organization_id).reserved_quantity == 10


def test_concurrent_reservations_at_the_limit_admit_only_what_fits(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    barrier = threading.Barrier(5)
    admitted: list[str] = []
    refused: list[str] = []

    def attempt(index: int) -> None:
        barrier.wait()
        try:
            _reserve(organization_id, f"limit-{index}", 30)
            admitted.append(f"limit-{index}")
        except BudgetExceededError:
            refused.append(f"limit-{index}")

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(admitted) == 3
    assert len(refused) == 2
    assert _budget_row(organization_id).reserved_quantity == 90


# --- Expiry and cleanup -------------------------------------------------------------------------


def test_an_unsettled_reservation_is_released_at_expiry_and_its_budget_returns(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    event_id = _reserve(organization_id, "stuck-1", 60)

    with SessionLocal() as db:
        released = release_expired(db, now=datetime.now(UTC) + timedelta(days=1))
        db.commit()

    # Cleanup is platform-wide, so other organizations' expired entries may be released too.
    assert released >= 1
    assert _budget_row(organization_id).reserved_quantity == 0
    with SessionLocal() as db:
        event = db.get(AiUsageEvent, event_id)
        assert event is not None
        assert event.status == AiUsageEvent.STATUS_RELEASED
        assert event.release_reason == "expired"
        audit = db.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(event_id)))
        assert audit is not None and audit.action == "usage.reservation.expired"
        assert json.loads(audit.event_metadata) == {"reserved_quantity": 60, "unit": UNIT.value}


def test_a_reservation_that_has_not_expired_is_left_alone(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _reserve(organization_id, "fresh-1", 40)

    with SessionLocal() as db:
        assert release_expired(db, now=datetime.now(UTC)) == 0
        db.commit()
    assert _budget_row(organization_id).reserved_quantity == 40


def test_cleanup_is_idempotent_and_never_counts_an_entry_twice(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _reserve(organization_id, "stuck-2", 25)
    later = datetime.now(UTC) + timedelta(days=1)

    with SessionLocal() as db:
        first = release_expired(db, now=later)
        db.commit()
    with SessionLocal() as db:
        second = release_expired(db, now=later)
        db.commit()

    assert (first, second) == (1, 0)
    assert _budget_row(organization_id).reserved_quantity == 0


def test_settling_an_expired_reservation_is_refused_so_the_budget_is_not_double_counted(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _reserve(organization_id, "late-settle", 30)
    with SessionLocal() as db:
        release_expired(db, now=datetime.now(UTC) + timedelta(days=1))
        db.commit()

    with SessionLocal() as db:
        with pytest.raises(InvalidUsageStateError):
            settle(db, organization_id=organization_id, idempotency_key="late-settle", actual_quantity=30)
        db.rollback()
    budget = _budget_row(organization_id)
    assert budget.reserved_quantity == 0
    assert budget.consumed_quantity == 0


def test_the_cleanup_job_releases_expired_entries_and_reports_failures(org, monkeypatch) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _reserve(organization_id, "job-1", 10)
    _reserve(organization_id, "job-2", 20)

    report = usage_maintenance.run(SessionLocal, now=datetime.now(UTC) + timedelta(days=1), batch_size=1)
    assert report["released"] == 2
    assert _budget_row(organization_id).reserved_quantity == 0

    def broken(db, *, now, limit):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(usage_maintenance, "release_expired", broken)
    failed = usage_maintenance.run(SessionLocal, now=datetime.now(UTC))
    assert failed["failed"] == 1


# --- Budget exhaustion and recovery ----------------------------------------------------------


def test_exhausted_budget_refuses_new_work_until_capacity_is_released(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 50)
    _reserve(organization_id, "exhaust-1", 50)

    with SessionLocal() as db:
        with pytest.raises(BudgetExceededError):
            reserve(
                db,
                organization_id=organization_id,
                unit=UNIT,
                quantity=1,
                idempotency_key="exhaust-2",
                occurred_at=NOW,
            )
        db.rollback()

    with SessionLocal() as db:
        release(db, organization_id=organization_id, idempotency_key="exhaust-1", reason="failed")
        db.commit()
    _reserve(organization_id, "exhaust-3", 50)
    assert _budget_row(organization_id).reserved_quantity == 50


# --- Thresholds ---------------------------------------------------------------------------------


def test_configured_thresholds_drive_the_alerts(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100, warning=50, critical=60)

    _reserve(organization_id, "t-1", 49)
    _reserve(organization_id, "t-2", 1)   # reaches 50, the configured warning
    _reserve(organization_id, "t-3", 10)  # reaches 60, the configured critical

    assert _threshold_events(organization_id) == [50, 60]


def test_repeated_crossings_do_not_duplicate_alerts(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100, warning=50, critical=60)
    _reserve(organization_id, "d-1", 55)
    _reserve(organization_id, "d-2", 1)
    _reserve(organization_id, "d-3", 1)

    assert _threshold_events(organization_id) == [50]


@pytest.mark.parametrize(("warning", "critical"), [(0, 85), (85, 70), (70, 100), (70, 70)])
def test_invalid_threshold_pairs_are_refused(org, warning, critical) -> None:
    organization_id, _ = org
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            configure_budget(
                db,
                organization_id=organization_id,
                unit=UNIT,
                limit_quantity=100,
                moment=NOW,
                warning_percent=warning,
                critical_percent=critical,
            )
        db.rollback()


def test_the_default_thresholds_are_70_and_85(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    with SessionLocal() as db:
        status = budget_status(db, organization_id=organization_id, unit=UNIT, moment=NOW)
    assert status is not None
    assert (status.warning_percent, status.critical_percent) == (70, 85)


# --- Breakdowns -----------------------------------------------------------------------------------


def test_breakdowns_group_by_capability_unit_and_provider_and_exclude_released_work(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 1000)
    _budget(organization_id, 1000, unit=UsageUnit.PROVIDER_COST_MINOR)
    _reserve(organization_id, "b-1", 100, capability="ai.assistant")
    _reserve(organization_id, "b-2", 40, capability="ai.assistant")
    _reserve(organization_id, "b-3", 5)  # unattributed
    _reserve(organization_id, "b-cost", 300, unit=UsageUnit.PROVIDER_COST_MINOR, capability="ai.assistant")
    with SessionLocal() as db:
        release(db, organization_id=organization_id, idempotency_key="b-2")
        db.commit()

    with SessionLocal() as db:
        by_capability = usage_breakdown(db, organization_id=organization_id, moment=NOW, group_by="capability")
        by_unit = usage_breakdown(db, organization_id=organization_id, moment=NOW, group_by="unit")

    capability_rows = {(row.group, row.unit): row.reserved_quantity for row in by_capability}
    assert capability_rows == {
        ("ai.assistant", UNIT.value): 100,
        ("ai.assistant", UsageUnit.PROVIDER_COST_MINOR.value): 300,
        ("unattributed", UNIT.value): 5,
    }
    # Provider cost is never summed with tokens.
    assert {row.unit for row in by_unit} == {UNIT.value, UsageUnit.PROVIDER_COST_MINOR.value}


def test_breakdowns_are_organization_scoped(org) -> None:
    organization_id, _ = org
    _other_user, other_organization = create_manager(permissions=())
    try:
        _budget(organization_id, 1000)
        _budget(other_organization.id, 1000)
        _reserve(organization_id, "mine", 10, capability="ai.assistant")
        _reserve(other_organization.id, "theirs", 999, capability="ai.assistant")

        with SessionLocal() as db:
            rows = usage_breakdown(db, organization_id=organization_id, moment=NOW, group_by="capability")
        assert sum(row.reserved_quantity for row in rows) == 10
    finally:
        with SessionLocal() as db:
            for model in (AiUsageEvent, OrganizationUsageBudget):
                db.execute(delete(model).where(model.organization_id == other_organization.id))
            db.commit()


# --- Execution gate integration ---------------------------------------------------------------------


def _enable_capability(organization_id: UUID, user_id: UUID) -> None:
    with SessionLocal() as db:
        for key in (AUTOMATION_MASTER, AUTOMATION_DEAL_CREATED_RULES):
            set_capability_enabled(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                capability_key=key,
                is_enabled=True,
            )
        db.commit()


def _gate(organization_id: UUID, user_id: UUID, *, key: str, quantity: int, context=None):
    with SessionLocal() as db:
        from app.db.models.user import User

        user = db.get(User, user_id)
        assert user is not None
        actor = context or attested_user_context(user, organization_id=organization_id)
        decision = authorize_execution(
            db,
            ExecutionRequest(
                organization_id=organization_id,
                capability_key=AUTOMATION_DEAL_CREATED_RULES,
                actor=actor,
                resource_type="deal",
                resource_id=str(uuid4()),
                resource_organization_id=organization_id,
                resource_active=True,
                required_permission=None,
                billable=True,
                budget=BudgetReservation(unit=UNIT, quantity=quantity, idempotency_key=key),
            ),
        )
        db.commit()
        return decision


def test_billable_work_reserves_budget_through_the_gate(org) -> None:
    organization_id, user_id = org
    _enable_capability(organization_id, user_id)
    _budget(organization_id, 100)

    decision = _gate(organization_id, user_id, key="gate-1", quantity=40)

    assert decision.allowed is True
    assert _budget_row(organization_id).reserved_quantity == 40
    with SessionLocal() as db:
        event = db.scalar(select(AiUsageEvent).where(AiUsageEvent.idempotency_key == "gate-1"))
        assert event is not None and event.capability_key == AUTOMATION_DEAL_CREATED_RULES


def test_gate_denies_billable_work_when_the_budget_is_exhausted_and_reserves_nothing(org) -> None:
    organization_id, user_id = org
    _enable_capability(organization_id, user_id)
    _budget(organization_id, 10)

    decision = _gate(organization_id, user_id, key="gate-big", quantity=50)

    assert decision.allowed is False
    assert decision.reason_code == "budget_exhausted"
    assert _budget_row(organization_id).reserved_quantity == 0


def test_gate_denies_billable_work_when_no_budget_is_configured(org) -> None:
    organization_id, user_id = org
    _enable_capability(organization_id, user_id)

    decision = _gate(organization_id, user_id, key="gate-none", quantity=5)

    assert decision.reason_code == "budget_not_configured"


def test_gate_denies_a_reused_key_with_different_usage(org) -> None:
    organization_id, user_id = org
    _enable_capability(organization_id, user_id)
    _budget(organization_id, 100)
    _gate(organization_id, user_id, key="gate-dup", quantity=10)

    decision = _gate(organization_id, user_id, key="gate-dup", quantity=20)

    assert decision.reason_code == "usage_key_conflict"
    assert _budget_row(organization_id).reserved_quantity == 10


def test_entitlement_removed_during_execution_stops_the_run_and_the_caller_releases_usage(org) -> None:
    organization_id, user_id = org
    _enable_capability(organization_id, user_id)
    _budget(organization_id, 100)
    allowed = _gate(organization_id, user_id, key="inflight-1", quantity=30)
    assert allowed.allowed is True

    with SessionLocal() as db:
        from app.db.models.user import User

        user = db.get(User, user_id)
        assert user is not None
        revoked = attested_user_context(
            user,
            organization_id=organization_id,
            entitlements=[{"feature_key": "workflow_automation", "enabled": False}],
        )
    stopped = _gate(organization_id, user_id, key="inflight-2", quantity=5, context=revoked)

    assert stopped.allowed is False
    assert stopped.reason_code == "entitlement_disabled"
    # The stopped step never reserved. The caller releases the earlier reservation when it stops.
    with SessionLocal() as db:
        release(db, organization_id=organization_id, idempotency_key="inflight-1", reason="entitlement_removed")
        db.commit()
    budget = _budget_row(organization_id)
    assert budget.reserved_quantity == 0
    assert budget.consumed_quantity == 0


# --- Duplicate threshold alerts are prevented through the outbox -------------------------------------


def test_a_threshold_is_announced_once_per_period_even_after_settlement(org) -> None:
    organization_id, _ = org
    _budget(organization_id, 100)
    _reserve(organization_id, "settle-alert", 75)
    with SessionLocal() as db:
        settle(db, organization_id=organization_id, idempotency_key="settle-alert", actual_quantity=75)
        db.commit()

    assert _threshold_events(organization_id) == [70]


def test_the_settings_default_reservation_ttl_is_fifteen_minutes() -> None:
    assert get_settings().usage_reservation_ttl_seconds == 900

