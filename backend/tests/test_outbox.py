"""Tests for the transactional outbox foundation (DFR1-013)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import Base
from app.db.models.organization import Organization
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal, engine
from app.outbox import reporting
from app.outbox.service import (
    InvalidOutboxEventError,
    OutboxConflictError,
    dispatch_due_events,
    enqueue_event,
    mark_failed,
    register_handler,
    unregister_handler,
)
from app.outbox.worker import main as worker_main

TEST_EVENT_TYPE = "test.outbox.created"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_outbox() -> Generator[None]:
    """Give each test an empty outbox so dispatch counts are exact.

    The conftest refuses to run against any database except dealflow_test.
    """
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.execute(delete(OutboxEvent))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(OutboxEvent))
        db.commit()


@pytest.fixture
def organization_id() -> Generator:
    with SessionLocal() as db:
        organization = Organization(name=f"Outbox Test {uuid4()}", is_active=True)
        db.add(organization)
        db.commit()
        org_id = organization.id
    yield org_id
    with SessionLocal() as db:
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == org_id))
        db.execute(delete(Organization).where(Organization.id == org_id))
        db.commit()


def _enqueue(db: Session, organization_id, *, key: str | None = None, **overrides):
    values = {
        "organization_id": organization_id,
        "event_type": TEST_EVENT_TYPE,
        "aggregate_type": "lead",
        "aggregate_id": "lead-1",
        "idempotency_key": key or f"key-{uuid4()}",
        "payload": {"lead_id": "lead-1", "status": "NEW"},
        "correlation_id": "corr-1",
        # Dispatch in these tests runs at NOW. Using the wall clock here would make
        # events due only after NOW, depending on when the suite runs.
        "available_at": NOW,
    }
    values.update(overrides)
    return enqueue_event(db, **values)


@pytest.fixture
def handler_log() -> Generator[list[str]]:
    calls: list[str] = []
    yield calls
    unregister_handler(TEST_EVENT_TYPE)


def _register_success(calls: list[str]) -> None:
    def handler(_db: Session, event: OutboxEvent) -> None:
        calls.append(str(event.id))

    register_handler(TEST_EVENT_TYPE, handler)


# Enqueue semantics -----------------------------------------------------------


def test_enqueue_creates_pending_event_with_default_attempt_budget(
    organization_id,
) -> None:
    with SessionLocal() as db:
        event = _enqueue(db, organization_id)
        db.commit()
        event_id = event.id

    with SessionLocal() as db:
        stored = db.get(OutboxEvent, event_id)
        assert stored is not None
        assert stored.status == OutboxEvent.STATUS_PENDING
        assert stored.attempts == 0
        assert stored.max_attempts == get_settings().outbox_max_attempts
        assert stored.payload == {"lead_id": "lead-1", "status": "NEW"}


def test_event_is_discarded_when_the_business_transaction_rolls_back(
    organization_id,
) -> None:
    key = f"rollback-{uuid4()}"
    with SessionLocal() as db:
        _enqueue(db, organization_id, key=key)
        db.rollback()

    with SessionLocal() as db:
        assert (
            db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == key))
            is None
        )


def test_duplicate_idempotency_key_returns_the_stored_event(organization_id) -> None:
    key = f"dup-{uuid4()}"
    with SessionLocal() as db:
        first = _enqueue(db, organization_id, key=key)
        db.commit()
        first_id = first.id

    with SessionLocal() as db:
        second = _enqueue(db, organization_id, key=key)
        db.commit()
        assert second.id == first_id

    with SessionLocal() as db:
        rows = db.scalars(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
        ).all()
        assert len(rows) == 1


def test_idempotency_key_reused_for_another_tenant_is_rejected(organization_id) -> None:
    key = f"tenant-{uuid4()}"
    with SessionLocal() as db:
        _enqueue(db, organization_id, key=key)
        db.commit()

    other_org = uuid4()
    with SessionLocal() as db, pytest.raises(OutboxConflictError):
        _enqueue(db, other_org, key=key)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"event_type": "NotDotted"}, "lowercase dotted"),
        ({"event_type": "lead"}, "lowercase dotted"),
        ({"aggregate_type": " "}, "aggregate_type"),
        ({"idempotency_key": "x" * 201}, "idempotency_key"),
        ({"payload": {"value": object()}}, "JSON-serializable"),
        ({"payload": {"blob": "x" * (65 * 1024)}}, "size limit"),
        ({"schema_version": 0}, "schema_version"),
        ({"max_attempts": 0}, "max_attempts"),
    ],
)
def test_malformed_events_are_rejected(organization_id, overrides, message) -> None:
    with SessionLocal() as db, pytest.raises(InvalidOutboxEventError, match=message):
        _enqueue(db, organization_id, **overrides)


# Dispatch --------------------------------------------------------------------


def test_dispatch_runs_the_handler_once_and_marks_delivery(
    organization_id, handler_log
) -> None:
    _register_success(handler_log)
    with SessionLocal() as db:
        event = _enqueue(db, organization_id)
        db.commit()
        event_id = event.id

    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="test-worker", now=NOW, batch_size=10
        )
    assert result.claimed == 1
    assert result.delivered == 1
    assert handler_log == [str(event_id)]

    with SessionLocal() as db:
        stored = db.get(OutboxEvent, event_id)
        assert stored.status == OutboxEvent.STATUS_DELIVERED
        assert stored.delivered_at is not None
        assert stored.locked_by is None
        assert stored.last_error is None

    with SessionLocal() as db:
        again = dispatch_due_events(db, worker_id="test-worker", now=NOW, batch_size=10)
    assert again.claimed == 0
    assert handler_log == [str(event_id)]


def test_failed_handler_writes_are_rolled_back_and_event_is_retried(
    organization_id, handler_log
) -> None:
    child_key = f"child-{uuid4()}"

    def handler(db: Session, event: OutboxEvent) -> None:
        _enqueue(db, organization_id, key=child_key, aggregate_id="child")
        raise RuntimeError("provider timed out")

    register_handler(TEST_EVENT_TYPE, handler)
    with SessionLocal() as db:
        event = _enqueue(db, organization_id)
        db.commit()
        event_id = event.id

    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="test-worker", now=NOW, batch_size=10
        )
    assert result.retried == 1
    assert result.delivered == 0

    with SessionLocal() as db:
        assert (
            db.scalar(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == child_key)
            )
            is None
        )
        stored = db.get(OutboxEvent, event_id)
        assert stored.status == OutboxEvent.STATUS_PENDING
        assert stored.attempts == 1
        assert stored.last_error == "RuntimeError: provider timed out"
        assert stored.available_at > NOW


def test_event_is_dead_lettered_after_its_attempt_budget_is_spent(
    organization_id, handler_log
) -> None:
    def handler(_db: Session, _event: OutboxEvent) -> None:
        raise ConnectionError("downstream unavailable")

    register_handler(TEST_EVENT_TYPE, handler)
    with SessionLocal() as db:
        event = _enqueue(db, organization_id, max_attempts=2)
        db.commit()
        event_id = event.id

    cycle_time = NOW
    for _ in range(2):
        with SessionLocal() as db:
            dispatch_due_events(
                db, worker_id="test-worker", now=cycle_time, batch_size=10
            )
        cycle_time += timedelta(days=1)

    with SessionLocal() as db:
        stored = db.get(OutboxEvent, event_id)
        assert stored.status == OutboxEvent.STATUS_DEAD_LETTER
        assert stored.attempts == 2
        assert stored.last_error == "ConnectionError: downstream unavailable"

    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="test-worker", now=cycle_time, batch_size=10
        )
    assert result.claimed == 0


def test_event_without_a_registered_handler_fails_closed(organization_id) -> None:
    with SessionLocal() as db:
        event = _enqueue(db, organization_id, max_attempts=1)
        db.commit()
        event_id = event.id

    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="test-worker", now=NOW, batch_size=10
        )
    assert result.dead_lettered == 1

    with SessionLocal() as db:
        stored = db.get(OutboxEvent, event_id)
        assert stored.status == OutboxEvent.STATUS_DEAD_LETTER
        assert stored.last_error.startswith("UnknownEventTypeError:")


def test_claimed_event_is_not_reclaimed_until_its_lease_expires(
    organization_id, handler_log
) -> None:
    def slow_handler(_db: Session, _event: OutboxEvent) -> None:
        raise TimeoutError("still running elsewhere")

    register_handler(TEST_EVENT_TYPE, slow_handler)
    with SessionLocal() as db:
        event = _enqueue(db, organization_id, max_attempts=5)
        db.commit()
        event_id = event.id

    lease = get_settings().outbox_lease_seconds
    from app.outbox.service import claim_due_events

    with SessionLocal() as db:
        first = claim_due_events(
            db, worker_id="worker-a", now=NOW, limit=10, lease_seconds=lease
        )
        db.commit()
        assert [e.id for e in first] == [event_id]

    with SessionLocal() as db:
        during_lease = claim_due_events(
            db,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=1),
            limit=10,
            lease_seconds=lease,
        )
        db.commit()
        assert during_lease == []

    after_lease = NOW + timedelta(seconds=lease + 1)
    with SessionLocal() as db:
        recovered = claim_due_events(
            db, worker_id="worker-b", now=after_lease, limit=10, lease_seconds=lease
        )
        db.commit()
        assert [e.id for e in recovered] == [event_id]
        assert recovered[0].locked_by == "worker-b"
        assert recovered[0].attempts == 2


def test_unknown_event_types_do_not_block_other_events(
    organization_id, handler_log
) -> None:
    _register_success(handler_log)
    with SessionLocal() as db:
        _enqueue(db, organization_id, event_type="test.unknown.event")
        good = _enqueue(db, organization_id)
        db.commit()
        good_id = good.id

    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="test-worker", now=NOW, batch_size=10
        )
    assert result.claimed == 2
    assert result.delivered == 1
    assert handler_log == [str(good_id)]


# Backoff and error handling --------------------------------------------------


def test_backoff_grows_exponentially_and_is_capped() -> None:
    event = OutboxEvent(
        event_type=TEST_EVENT_TYPE,
        aggregate_type="lead",
        aggregate_id="lead-1",
        idempotency_key="unit-backoff",
        payload={},
        attempts=1,
        max_attempts=50,
    )

    delays = []
    for attempt in range(1, 8):
        event.attempts = attempt
        mark_failed(
            event,
            exc=RuntimeError("boom"),
            now=NOW,
            base_backoff_seconds=30,
            max_backoff_seconds=300,
        )
        delays.append(int((event.available_at - NOW).total_seconds()))

    assert delays == [30, 60, 120, 240, 300, 300, 300]


def test_error_text_is_single_line_and_bounded() -> None:
    event = OutboxEvent(
        event_type=TEST_EVENT_TYPE,
        aggregate_type="lead",
        aggregate_id="lead-1",
        idempotency_key="unit-error",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    mark_failed(
        event,
        exc=RuntimeError("line one\nline two\r" + "x" * 2000),
        now=NOW,
        base_backoff_seconds=1,
        max_backoff_seconds=10,
    )
    assert "\n" not in event.last_error and "\r" not in event.last_error
    assert len(event.last_error) <= 500


# Operator reporting and worker -----------------------------------------------


def test_reporting_is_scoped_to_one_organization_and_hides_payloads(
    organization_id,
) -> None:
    with SessionLocal() as db:
        _enqueue(db, organization_id, payload={"secret_note": "do-not-print"})
        db.commit()

    with SessionLocal() as db:
        scoped = reporting.list_events(db, organization_id=organization_id, limit=10)
        other = reporting.list_events(db, organization_id=uuid4(), limit=10)
    assert len(scoped) == 1
    assert other == []
    assert "do-not-print" not in reporting._format_row(scoped[0])


@pytest.mark.parametrize(("limit", "status"), [(0, None), (201, None), (10, "bogus")])
def test_reporting_rejects_invalid_filters(limit, status) -> None:
    with SessionLocal() as db, pytest.raises(ValueError):
        reporting.list_events(db, status=status, limit=limit)


def test_worker_cli_runs_one_cycle_and_exits_zero() -> None:
    assert worker_main(["--once"]) == 0


def test_worker_cli_rejects_non_positive_poll_interval() -> None:
    with pytest.raises(SystemExit):
        worker_main(["--poll-interval", "0"])
