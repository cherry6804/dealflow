"""Configurable AI usage alert thresholds: validation, enforcement, delivery and permissions (WS6 WP2).

Runs on PostgreSQL. Concurrency cases use real threads with separate committed sessions, and alerts
are dispatched through the real outbox with the governance handler registered, as the worker does.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.governance import router as governance_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.notification import Notification
from app.db.models.organization_usage_alert_settings import (
    OrganizationUsageAlertSettings,
)
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal, get_db_session
from app.governance.alert_delivery import (
    ALERT_NOTIFICATION_EVENT_TYPE,
    deliver_usage_threshold_alert,
    register_governance_handlers,
)
from app.governance.alert_threshold_service import (
    THRESHOLD_SETTINGS_ACTION,
    update_alert_thresholds,
)
from app.governance.alert_thresholds import (
    DEFAULT_ALERT_THRESHOLDS,
    InvalidAlertThresholdsError,
    read_alert_thresholds,
    validate_alert_thresholds,
)
from app.governance.usage_ledger import (
    THRESHOLD_EVENT_TYPE,
    UsageError,
    UsageUnit,
    change_budget,
    configure_budget,
    reserve,
)
from app.outbox.service import dispatch_due_events, unregister_handler
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
NEXT_MONTH = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
UNIT = UsageUnit.TOKENS_OUTPUT
API = "/api/v1/governance/usage/alert-thresholds"


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(Notification).where(Notification.organization_id == organization_id))
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization_id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        db.execute(delete(OrganizationUsageAlertSettings).where(
            OrganizationUsageAlertSettings.organization_id == organization_id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


@pytest.fixture
def handlers() -> Iterator[None]:
    register_governance_handlers()
    yield
    unregister_handler(THRESHOLD_EVENT_TYPE)


@pytest.fixture
def owned() -> Iterator[tuple[UUID, UUID]]:
    """An organization with an owner, who may change thresholds."""
    owner, organization = create_owner_manager(permissions=("governance.budgets.manage",))
    yield organization.id, owner.id
    _cleanup(organization.id)


@pytest.fixture
def other_org() -> Iterator[UUID]:
    _, organization = create_manager(permissions=())
    yield organization.id
    _cleanup(organization.id)


def _run(fn: Callable, *args, **kwargs):
    with SessionLocal() as db:
        db.expire_on_commit = False
        result = fn(db, *args, **kwargs)
        db.commit()
        return result


def _budget(organization_id: UUID, limit: int, moment: datetime = NOW, unit: UsageUnit = UNIT) -> None:
    _run(configure_budget, organization_id=organization_id, unit=unit, limit_quantity=limit, moment=moment)


def _reserve(organization_id: UUID, key: str, quantity: int, moment: datetime = NOW) -> None:
    _run(
        reserve,
        organization_id=organization_id,
        unit=UNIT,
        quantity=quantity,
        idempotency_key=key,
        occurred_at=moment,
        now=moment,
    )


def _set_thresholds(organization_id: UUID, owner_id: UUID, values, moment: datetime = NOW):
    return _run(
        update_alert_thresholds,
        organization_id=organization_id,
        actor_user_id=owner_id,
        values=values,
        moment=moment,
    )


def _threshold_payloads(organization_id: UUID) -> list[int]:
    with SessionLocal() as db:
        return sorted(
            row.payload["threshold_percent"]
            for row in db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.organization_id == organization_id,
                    OutboxEvent.event_type == THRESHOLD_EVENT_TYPE,
                )
            ).all()
        )


def _dispatch_all() -> None:
    with SessionLocal() as db:
        dispatch_due_events(
            db, worker_id="threshold-test", now=datetime.now(UTC) + timedelta(minutes=5), batch_size=100
        )
        db.commit()


def _covered(organization_id: UUID, moment: datetime = NOW) -> list[int]:
    with SessionLocal() as db:
        budget = db.scalar(
            select(OrganizationUsageBudget).where(
                OrganizationUsageBudget.organization_id == organization_id,
                OrganizationUsageBudget.unit == UNIT.value,
                OrganizationUsageBudget.period_start == moment.replace(day=1).date(),
            )
        )
        return sorted(budget.alerted_thresholds)


def _alert_notification_count(organization_id: UUID) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Notification.id).where(
            Notification.organization_id == organization_id,
            Notification.event_type == ALERT_NOTIFICATION_EVENT_TYPE,
        )).all())


# --- Defaults and validation ----------------------------------------------------------------------


def test_an_organization_without_a_row_uses_the_defaults(owned) -> None:
    organization_id, _ = owned
    with SessionLocal() as db:
        result = read_alert_thresholds(db, organization_id=organization_id)

    assert result.values == DEFAULT_ALERT_THRESHOLDS == (70, 85, 100)
    assert result.is_default is True
    assert result.version == 0


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ([70, 85], "wrong_count"),
        ([70, 85, 100, 100], "wrong_count"),
        ("70,85,100", "wrong_count"),
        ([True, 85, 100], "not_a_whole_number"),
        ([70.0, 85, 100], "not_a_whole_number"),
        (["70", 85, 100], "not_a_whole_number"),
        ([0, 85, 100], "out_of_range"),
        ([70, 85, 101], "out_of_range"),
        ([70, 70, 100], "not_strictly_increasing"),
        ([85, 70, 100], "not_strictly_increasing"),
        ([70, 85, 99], "top_threshold_must_be_100"),
    ],
)
def test_invalid_thresholds_are_refused_with_a_stable_reason(values, reason) -> None:
    with pytest.raises(InvalidAlertThresholdsError) as error:
        validate_alert_thresholds(values)
    assert error.value.reason_code == reason


def test_valid_thresholds_are_accepted() -> None:
    assert validate_alert_thresholds([1, 2, 100]) == (1, 2, 100)
    assert validate_alert_thresholds([50, 80, 100]) == (50, 80, 100)


def test_a_refused_change_writes_nothing_and_creates_no_audit(owned) -> None:
    organization_id, owner_id = owned
    with pytest.raises(InvalidAlertThresholdsError):
        _set_thresholds(organization_id, owner_id, [70, 70, 100])

    with SessionLocal() as db:
        assert db.scalar(select(OrganizationUsageAlertSettings.id).where(
            OrganizationUsageAlertSettings.organization_id == organization_id)) is None
        assert db.scalars(select(AuditEvent.id).where(
            AuditEvent.organization_id == organization_id,
            AuditEvent.action == THRESHOLD_SETTINGS_ACTION)).all() == []


# --- Storage, versioning and audit ---------------------------------------------------------------


def test_a_valid_change_is_stored_and_versioned(owned) -> None:
    organization_id, owner_id = owned
    first = _set_thresholds(organization_id, owner_id, [50, 80, 100])
    second = _set_thresholds(organization_id, owner_id, [60, 80, 100])

    assert first.values == (50, 80, 100) and first.version == 1
    assert second.values == (60, 80, 100) and second.version == 2
    assert second.is_default is False


def test_an_unchanged_value_writes_nothing(owned) -> None:
    organization_id, owner_id = owned
    _set_thresholds(organization_id, owner_id, [50, 80, 100])
    again = _set_thresholds(organization_id, owner_id, [50, 80, 100])

    assert again.version == 1
    with SessionLocal() as db:
        audits = db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == organization_id,
            AuditEvent.action == THRESHOLD_SETTINGS_ACTION)).all()
    # Only the first, real change writes records: one requested and one completed. The repeat writes none.
    assert sorted(item.outcome for item in audits) == ["completed", "requested"]


def test_a_change_is_audited_with_before_and_after_values(owned) -> None:
    organization_id, owner_id = owned
    _set_thresholds(organization_id, owner_id, [50, 80, 100])
    _set_thresholds(organization_id, owner_id, [60, 90, 100])

    with SessionLocal() as db:
        completed = sorted(
            db.scalars(select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == THRESHOLD_SETTINGS_ACTION,
                AuditEvent.outcome == "completed")).all(),
            key=lambda item: json.loads(item.event_metadata)["new_version"],
        )
    assert len(completed) == 2

    latest = json.loads(completed[-1].event_metadata)
    assert latest["before"] == [50, 80, 100]
    assert latest["after"] == [60, 90, 100]
    assert latest["previous_version"] == 1
    assert latest["new_version"] == 2
    assert completed[-1].user_id == owned[1]
    assert completed[-1].permission_key == "governance.budgets.manage"


# --- Enforcement on usage ------------------------------------------------------------------------


def test_alerts_follow_the_configured_thresholds(owned, handlers) -> None:
    organization_id, owner_id = owned
    _set_thresholds(organization_id, owner_id, [50, 80, 100])
    _budget(organization_id, 100)

    _reserve(organization_id, "cfg-a", 55)
    assert _threshold_payloads(organization_id) == [50]

    _reserve(organization_id, "cfg-b", 30)
    assert _threshold_payloads(organization_id) == [50, 80]


def test_the_default_thresholds_still_announce_70_85_and_100(owned) -> None:
    organization_id, _ = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "def-a", 70)
    _reserve(organization_id, "def-b", 15)
    _reserve(organization_id, "def-c", 15)

    assert _threshold_payloads(organization_id) == [70, 85, 100]


def test_lowering_a_threshold_announces_what_usage_already_reached(owned) -> None:
    organization_id, owner_id = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "reached", 60)
    assert _threshold_payloads(organization_id) == []

    # 60 is above the new 50 threshold, and no further usage arrives. It must still be announced.
    _set_thresholds(organization_id, owner_id, [50, 80, 100])

    assert _threshold_payloads(organization_id) == [50]


def test_a_budget_limit_reduction_announces_a_threshold_it_crosses(owned) -> None:
    organization_id, owner_id = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "limit-a", 60)
    assert _threshold_payloads(organization_id) == []

    _run(change_budget, organization_id=organization_id, actor_user_id=owner_id, unit=UNIT,
         limit_quantity=70, moment=NOW)

    # 60 of 70 is 85 percent, so the 70 and 85 thresholds are reached. Only the highest is queued.
    assert _threshold_payloads(organization_id) == [85]


def test_a_delivered_threshold_is_not_announced_again_after_a_change(owned, handlers) -> None:
    organization_id, owner_id = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "once-a", 70)
    _dispatch_all()
    assert _covered(organization_id) == [70]

    _set_thresholds(organization_id, owner_id, [60, 85, 100])
    _reserve(organization_id, "once-b", 1)

    # 70 was delivered and is covered. The new 60 threshold is a different threshold, so it is queued,
    # because usage has reached it. Nothing repeats 70.
    assert _threshold_payloads(organization_id) == [60, 70]


def test_a_repeated_request_queues_at_most_one_alert(owned) -> None:
    organization_id, _ = owned
    _budget(organization_id, 100)
    for _ in range(4):
        _reserve(organization_id, "repeat-same", 70)

    assert _threshold_payloads(organization_id) == [70]


# --- Delivery state ------------------------------------------------------------------------------


def test_delivery_covers_the_configured_thresholds_at_or_below_it(owned, handlers) -> None:
    organization_id, owner_id = owned
    _set_thresholds(organization_id, owner_id, [50, 80, 100])
    _budget(organization_id, 100)
    _reserve(organization_id, "cover-a", 80)
    _dispatch_all()

    # Usage is 80, so only the 80 alert is queued. Its delivery covers 50 and 80, and neither is
    # announced again. The 100 threshold is not reached yet, so it is not covered.
    assert _threshold_payloads(organization_id) == [80]
    assert _covered(organization_id) == [50, 80]
    assert _alert_notification_count(organization_id) >= 1


def test_redelivering_an_alert_creates_no_duplicate_notification(owned, handlers) -> None:
    organization_id, _ = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "redeliver-a", 70)

    with SessionLocal() as db:
        event = db.scalars(select(OutboxEvent).where(
            OutboxEvent.organization_id == organization_id,
            OutboxEvent.event_type == THRESHOLD_EVENT_TYPE)).one()
        deliver_usage_threshold_alert(db, event)
        db.commit()
    first = _alert_notification_count(organization_id)

    with SessionLocal() as db:
        event = db.scalars(select(OutboxEvent).where(
            OutboxEvent.organization_id == organization_id,
            OutboxEvent.event_type == THRESHOLD_EVENT_TYPE)).one()
        deliver_usage_threshold_alert(db, event)
        db.commit()

    assert first >= 1
    assert _alert_notification_count(organization_id) == first
    assert _covered(organization_id) == [70]


def test_a_queued_but_undelivered_alert_is_not_marked_covered(owned) -> None:
    organization_id, _ = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "queued-only", 70)

    # Queued is not delivered. Nothing may claim the threshold was covered or notified.
    assert _covered(organization_id) == []
    assert _alert_notification_count(organization_id) == 0


# --- Concurrency and rollover -------------------------------------------------------------------


def test_concurrent_usage_queues_exactly_one_alert_per_threshold(owned) -> None:
    organization_id, _ = owned
    _budget(organization_id, 100)
    barrier = threading.Barrier(7)
    errors: list[BaseException] = []

    def attempt(index: int) -> None:
        barrier.wait()
        try:
            _reserve(organization_id, f"parallel-{index}", 10)
        except UsageError as exc:  # any rule violation is collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(7)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert _threshold_payloads(organization_id) == [70]


def test_a_threshold_change_racing_usage_never_duplicates_or_skips(owned) -> None:
    organization_id, owner_id = owned
    _budget(organization_id, 100)
    _reserve(organization_id, "race-base", 60)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def change() -> None:
        barrier.wait()
        try:
            _set_thresholds(organization_id, owner_id, [50, 80, 100])
        except InvalidAlertThresholdsError as exc:
            errors.append(exc)

    def use() -> None:
        barrier.wait()
        try:
            _reserve(organization_id, "race-extra", 5)
        except UsageError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=change), threading.Thread(target=use)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    # Usage is 60 or 65 in either order. Both reach 50 and neither reaches 80. Exactly one 50 alert.
    assert _threshold_payloads(organization_id) == [50]


def test_a_new_period_starts_with_no_delivered_thresholds(owned, handlers) -> None:
    organization_id, _ = owned
    _budget(organization_id, 100, moment=NOW)
    _reserve(organization_id, "period-oct", 70)
    _dispatch_all()
    assert _covered(organization_id, NOW) == [70]

    _budget(organization_id, 100, moment=NEXT_MONTH)
    _reserve(organization_id, "period-nov", 70, moment=NEXT_MONTH)

    assert _covered(organization_id, NEXT_MONTH) == []
    assert _threshold_payloads(organization_id) == [70, 70]


# --- Tenant isolation ----------------------------------------------------------------------------


def test_one_tenants_thresholds_do_not_change_another_tenants_alerts(owned, other_org) -> None:
    organization_id, owner_id = owned
    _set_thresholds(organization_id, owner_id, [50, 80, 100])
    _budget(other_org, 100)
    _reserve(other_org, "tenant-b", 55)

    # The other organization keeps the defaults, and 55 is below the default 70, so nothing is queued.
    assert _threshold_payloads(other_org) == []
    with SessionLocal() as db:
        assert read_alert_thresholds(db, organization_id=other_org).is_default is True


# --- API and permissions -------------------------------------------------------------------------


def _app_for(user) -> FastAPI:
    app = FastAPI()
    app.include_router(governance_router)

    def db_override() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    return app


def test_the_owner_can_read_and_change_thresholds_through_the_api() -> None:
    owner, owner_org = create_owner_manager(permissions=("governance.budgets.manage",))
    try:
        with TestClient(_app_for(owner)) as client:
            client.headers.update({"X-Organization-ID": str(owner_org.id)})
            initial = client.get(API)
            changed = client.put(API, json={"thresholds": [50, 80, 100], "confirm": True})
            after = client.get(API)
    finally:
        _cleanup(owner_org.id)

    assert initial.status_code == 200 and initial.json()["is_default"] is True
    assert changed.status_code == 200, changed.text
    assert changed.json()["thresholds"] == [50, 80, 100]
    assert after.json()["thresholds"] == [50, 80, 100]


def test_a_reader_can_view_but_not_change_thresholds(owned) -> None:
    reader, reader_org = create_manager(permissions=("governance.usage.read",))
    try:
        with TestClient(_app_for(reader)) as client:
            client.headers.update({"X-Organization-ID": str(reader_org.id)})
            view = client.get(API)
            change = client.put(API, json={"thresholds": [50, 80, 100], "confirm": True})
    finally:
        _cleanup(reader_org.id)

    assert view.status_code == 200
    assert change.status_code == 403


def test_a_budget_manager_without_the_owner_role_cannot_change_thresholds(owned) -> None:
    manager, manager_org = create_manager(permissions=("governance.budgets.manage",))
    try:
        with TestClient(_app_for(manager)) as client:
            client.headers.update({"X-Organization-ID": str(manager_org.id)})
            change = client.put(API, json={"thresholds": [50, 80, 100], "confirm": True})
    finally:
        _cleanup(manager_org.id)

    # budgets.manage is owner-only, so a custom role holding the key must not be enough.
    assert change.status_code == 403


def test_an_invalid_api_change_is_refused_with_a_stable_code(owned) -> None:
    owner, owner_org = create_owner_manager(permissions=("governance.budgets.manage",))
    try:
        with TestClient(_app_for(owner)) as client:
            client.headers.update({"X-Organization-ID": str(owner_org.id)})
            response = client.put(API, json={"thresholds": [70, 70, 100], "confirm": True})
            current = client.get(API)
    finally:
        _cleanup(owner_org.id)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_strictly_increasing"
    assert current.json()["is_default"] is True


def test_a_change_without_confirmation_is_refused(owned) -> None:
    owner, owner_org = create_owner_manager(permissions=("governance.budgets.manage",))
    try:
        with TestClient(_app_for(owner)) as client:
            client.headers.update({"X-Organization-ID": str(owner_org.id)})
            response = client.put(API, json={"thresholds": [50, 80, 100]})
    finally:
        _cleanup(owner_org.id)

    assert response.status_code == 422
