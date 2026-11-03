"""Outbox worker operating model: fencing, retries, dead letters, replay, alert state and runtime (WS3).

Concurrency and recovery tests use real PostgreSQL connections. The crash test runs a separate
Python process and ends it without completing its claim, which is what a killed worker leaves.
"""

from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.notification import Notification
from app.db.models.organization import Organization
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.models.outbox_replay_record import OutboxReplayRecord
from app.db.session import SessionLocal, engine
from app.governance.alert_delivery import (
    ALERT_NOTIFICATION_EVENT_TYPE,
    REASON_NO_ADMINISTRATOR,
    register_governance_handlers,
)
from app.governance.usage_ledger import (
    THRESHOLD_EVENT_TYPE,
    UsageUnit,
    configure_budget,
    reserve,
)
from app.outbox import reporting
from app.outbox.replay import ReplayError, ReplayNotAuthorizedError, replay_dead_letter
from app.outbox.runtime import JsonLogFormatter, WorkerHealth, _ProbeServer, _run_loop
from app.outbox.service import (
    DEAD_LETTER_MAX_ATTEMPTS,
    EventHandler,
    PermanentHandlerError,
    apply_claim_transition,
    backoff_seconds,
    claim_due_events,
    delivered_values,
    dispatch_due_events,
    enqueue_event,
    lock_claim,
    register_handler,
    registered_event_types,
    unregister_handler,
)
from tests.test_deals_api import create_membership, create_user
from tests.test_team_api import TestingSessionLocal, attach_role

WORK_EVENT_TYPE = "test.ws3.work"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
ALLOWLIST = "ops-test"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_outbox() -> Generator[None]:
    Base.metadata.create_all(bind=engine)
    _wipe_outbox()
    yield
    _wipe_outbox()


def _wipe_outbox() -> None:
    with SessionLocal() as db:
        db.execute(delete(OutboxReplayRecord))
        db.execute(delete(OutboxEvent))
        db.commit()


@pytest.fixture
def organization_id() -> Generator[UUID]:
    with SessionLocal() as db:
        organization = Organization(name=f"WS3 Test {uuid4()}", is_active=True)
        db.add(organization)
        db.commit()
        org_id = organization.id
    yield org_id
    with SessionLocal() as db:
        db.execute(delete(Notification).where(Notification.organization_id == org_id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == org_id))
        db.execute(delete(OutboxReplayRecord).where(OutboxReplayRecord.organization_id == org_id))
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == org_id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == org_id))
        db.execute(delete(Organization).where(Organization.id == org_id))
        db.commit()


@pytest.fixture
def work_handler() -> Iterator[list[str]]:
    """Register a handler that records each event id it runs for."""
    calls: list[str] = []

    def handler(_db: Session, event: OutboxEvent) -> None:
        calls.append(str(event.id))

    _set_handler(handler)
    yield calls
    unregister_handler(WORK_EVENT_TYPE)


def _set_handler(handler: EventHandler) -> None:
    unregister_handler(WORK_EVENT_TYPE)
    register_handler(WORK_EVENT_TYPE, handler)


def _enqueue(db: Session, organization_id: UUID, *, max_attempts: int | None = None) -> UUID:
    event = enqueue_event(
        db,
        organization_id=organization_id,
        event_type=WORK_EVENT_TYPE,
        aggregate_type="lead",
        aggregate_id="lead-1",
        idempotency_key=f"ws3-{uuid4()}",
        payload={"lead_id": "lead-1"},
        correlation_id="corr-ws3",
        max_attempts=max_attempts,
        available_at=NOW,
    )
    db.commit()
    return event.id


def _stored(event_id: UUID) -> OutboxEvent:
    with SessionLocal() as db:
        event = db.get(OutboxEvent, event_id)
        db.expunge(event)
        return event


def _dispatch(worker: str, *, now: datetime = NOW, should_stop=None, rng=None):
    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id=worker, now=now, batch_size=50, should_stop=should_stop, rng=rng
        )
        db.commit()
        return result


# Fencing ---------------------------------------------------------------------


def test_a_taken_over_claim_cannot_record_its_outcome(organization_id, work_handler) -> None:
    with SessionLocal() as db:
        event_id = _enqueue(db, organization_id)

    with SessionLocal() as db:
        stale = claim_due_events(db, worker_id="stale-worker", now=NOW, limit=1, lease_seconds=60)
        stale_token = stale[0].claim_token
        db.commit()

    # The lease expires and another worker takes the event over and delivers it.
    later = NOW + timedelta(minutes=10)
    result = _dispatch("fresh-worker", now=later)
    assert result.delivered == 1

    with SessionLocal() as db:
        recorded = apply_claim_transition(
            db,
            event_id=event_id,
            worker_id="stale-worker",
            token=stale_token,
            values=delivered_values(now=later),
        )
        db.rollback()
    assert recorded is False
    assert _stored(event_id).status == OutboxEvent.STATUS_DELIVERED


def test_lock_claim_refuses_a_token_that_is_not_current(organization_id, work_handler) -> None:
    with SessionLocal() as db:
        event_id = _enqueue(db, organization_id)
    with SessionLocal() as db:
        claimed = claim_due_events(db, worker_id="worker-a", now=NOW, limit=1, lease_seconds=300)
        token = claimed[0].claim_token
        db.commit()

    with SessionLocal() as db:
        assert lock_claim(db, event_id=event_id, worker_id="worker-a", token=uuid4()) is False
        assert lock_claim(db, event_id=event_id, worker_id="worker-b", token=token) is False
        assert lock_claim(db, event_id=event_id, worker_id="worker-a", token=token) is True
        db.rollback()


def test_handler_writes_are_discarded_when_the_claim_is_lost_before_the_outcome(
    organization_id, work_handler
) -> None:
    """A handler that runs after its claim was taken over must not leave a delivered row behind."""
    with SessionLocal() as db:
        event_id = _enqueue(db, organization_id)
    with SessionLocal() as db:
        claimed = claim_due_events(db, worker_id="worker-a", now=NOW, limit=1, lease_seconds=300)
        token = claimed[0].claim_token
        db.commit()
    # Another worker's claim replaces worker-a's token after worker-a committed its claim.
    with SessionLocal() as db:
        event = db.get(OutboxEvent, event_id)
        event.claim_token = uuid4()
        db.commit()

    with SessionLocal() as db:
        assert apply_claim_transition(
            db, event_id=event_id, worker_id="worker-a", token=token, values=delivered_values(now=NOW)
        ) is False
        db.rollback()
    assert _stored(event_id).status == OutboxEvent.STATUS_PROCESSING


# Retries, permanent errors and dead letters ----------------------------------


def test_permanent_error_is_dead_lettered_at_once_with_its_reason(organization_id) -> None:
    def handler(_db: Session, _event: OutboxEvent) -> None:
        raise PermanentHandlerError("Configuration is missing.", reason_code=REASON_NO_ADMINISTRATOR)

    _set_handler(handler)
    try:
        with SessionLocal() as db:
            event_id = _enqueue(db, organization_id, max_attempts=5)
        result = _dispatch("worker-a")
    finally:
        unregister_handler(WORK_EVENT_TYPE)

    assert result.dead_lettered == 1
    stored = _stored(event_id)
    assert stored.status == OutboxEvent.STATUS_DEAD_LETTER
    assert stored.dead_letter_reason == REASON_NO_ADMINISTRATOR
    assert stored.attempts == 1
    assert stored.claim_token is None


def test_retryable_failure_backs_off_then_dead_letters_with_the_attempt_reason(
    organization_id,
) -> None:
    def handler(_db: Session, _event: OutboxEvent) -> None:
        raise RuntimeError("temporary outage")

    _set_handler(handler)
    try:
        with SessionLocal() as db:
            event_id = _enqueue(db, organization_id, max_attempts=2)
        first = _dispatch("worker-a", now=NOW)
        assert first.retried == 1
        pending = _stored(event_id)
        assert pending.status == OutboxEvent.STATUS_PENDING
        assert pending.available_at > NOW

        second = _dispatch("worker-a", now=NOW + timedelta(days=1))
        assert second.dead_lettered == 1
    finally:
        unregister_handler(WORK_EVENT_TYPE)

    stored = _stored(event_id)
    assert stored.status == OutboxEvent.STATUS_DEAD_LETTER
    assert stored.dead_letter_reason == DEAD_LETTER_MAX_ATTEMPTS
    assert stored.attempts == 2


def test_jittered_backoff_stays_between_half_and_the_full_capped_delay() -> None:
    for seed in range(200):
        delay = backoff_seconds(
            3, base_backoff_seconds=30, max_backoff_seconds=3600, rng=random.Random(seed)
        )
        assert 60 <= delay <= 120  # 30 * 2**2 = 120 is the cap for this attempt
    assert backoff_seconds(3, base_backoff_seconds=30, max_backoff_seconds=3600) == 120


# Shutdown ----------------------------------------------------------------------


def test_stop_request_returns_unstarted_claims_without_a_failed_attempt(
    organization_id, work_handler
) -> None:
    with SessionLocal() as db:
        ids = [_enqueue(db, organization_id) for _ in range(3)]

    result = _dispatch("worker-a", should_stop=lambda: True)

    assert result.claimed == 3
    assert result.released == 3
    assert work_handler == []
    for event_id in ids:
        stored = _stored(event_id)
        assert stored.status == OutboxEvent.STATUS_PENDING
        assert stored.attempts == 0
        assert stored.claim_token is None
        assert stored.locked_by is None


# Concurrency and crash recovery ---------------------------------------------------


def test_four_concurrent_workers_deliver_every_event_exactly_once(
    organization_id, work_handler
) -> None:
    with SessionLocal() as db:
        ids = {str(_enqueue(db, organization_id)) for _ in range(60)}

    errors: list[BaseException] = []

    def run(worker: str) -> None:
        try:
            while True:
                result = _dispatch(worker)
                if result.claimed == 0:
                    return
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(f"worker-{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert errors == []
    assert len(work_handler) == 60
    assert set(work_handler) == ids
    with SessionLocal() as db:
        statuses = {row[0] for row in db.execute(select(OutboxEvent.status).where(
            OutboxEvent.organization_id == organization_id))}
    assert statuses == {OutboxEvent.STATUS_DELIVERED}


def test_an_event_claimed_by_a_crashed_process_is_recovered_after_its_lease(
    organization_id, work_handler
) -> None:
    with SessionLocal() as db:
        event_id = _enqueue(db, organization_id)

    script = (
        "import os\n"
        "from datetime import UTC, datetime\n"
        "from app.db.session import SessionLocal\n"
        "from app.outbox.service import claim_due_events\n"
        "with SessionLocal() as db:\n"
        "    claim_due_events(db, worker_id='crashed', now=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),\n"
        "                     limit=1, lease_seconds=300)\n"
        "    db.commit()\n"
        "os._exit(0)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-500:]
    stored = _stored(event_id)
    assert stored.status == OutboxEvent.STATUS_PROCESSING
    assert stored.locked_by == "crashed"

    # Before the lease expires the event is still held.
    assert _dispatch("recovery-worker", now=NOW + timedelta(seconds=60)).claimed == 0
    assert work_handler == []

    # After the lease expires another worker recovers it and the handler runs once.
    result = _dispatch("recovery-worker", now=NOW + timedelta(minutes=10))
    assert result.delivered == 1
    assert work_handler == [str(event_id)]


# Operator replay -----------------------------------------------------------------


def _dead_letter(organization_id: UUID, reason: str = "permanent_error") -> UUID:
    def handler(_db: Session, _event: OutboxEvent) -> None:
        raise PermanentHandlerError("Configuration is missing.", reason_code=reason)

    # The failing handler stays registered, so replay tests can check the handler gate.
    _set_handler(handler)
    with SessionLocal() as db:
        event_id = _enqueue(db, organization_id)
    _dispatch("worker-a")
    assert _stored(event_id).status == OutboxEvent.STATUS_DEAD_LETTER
    return event_id


def _replay(event_id: UUID, organization_id: UUID, *, allowlist: str = ALLOWLIST,
            operator: str = ALLOWLIST, dry_run: bool = False, reason: str = "Corrected configuration"):
    with SessionLocal() as db:
        try:
            return replay_dead_letter(
                db,
                event_id=event_id,
                organization_id=organization_id,
                operator=operator,
                reason=reason,
                dry_run=dry_run,
                allowlist=allowlist,
            )
        finally:
            db.rollback()


def test_replay_is_refused_for_an_operator_not_on_the_allowlist(organization_id, work_handler) -> None:
    event_id = _dead_letter(organization_id)
    with pytest.raises(ReplayNotAuthorizedError):
        _replay(event_id, organization_id, allowlist="someone-else")
    with pytest.raises(ReplayNotAuthorizedError):
        _replay(event_id, organization_id, allowlist="")
    assert _stored(event_id).status == OutboxEvent.STATUS_DEAD_LETTER


def test_replay_refuses_another_tenants_event_with_the_same_message_as_an_unknown_one(
    organization_id, work_handler
) -> None:
    event_id = _dead_letter(organization_id)
    other_organization = uuid4()
    with pytest.raises(ReplayError) as cross_tenant:
        _replay(event_id, other_organization)
    with pytest.raises(ReplayError) as unknown:
        _replay(uuid4(), organization_id)
    assert str(cross_tenant.value) == str(unknown.value)
    assert _stored(event_id).status == OutboxEvent.STATUS_DEAD_LETTER


def test_dry_run_reports_the_change_without_making_it(organization_id, work_handler) -> None:
    event_id = _dead_letter(organization_id)
    outcome = _replay(event_id, organization_id, dry_run=True)
    assert outcome.replayed is False
    assert outcome.status == OutboxEvent.STATUS_DEAD_LETTER
    assert _stored(event_id).status == OutboxEvent.STATUS_DEAD_LETTER


def test_replay_requeues_once_writes_an_audit_record_and_the_handler_then_runs(
    organization_id, work_handler
) -> None:
    event_id = _dead_letter(organization_id, reason="permanent_error")
    outcome = _replay(event_id, organization_id)

    assert outcome.replayed is True
    stored = _stored(event_id)
    assert stored.status == OutboxEvent.STATUS_PENDING
    assert stored.attempts == 0
    assert stored.dead_letter_reason is None
    with SessionLocal() as db:
        records = list(db.scalars(select(OutboxReplayRecord).where(OutboxReplayRecord.event_id == event_id)))
    assert len(records) == 1
    assert records[0].operator == ALLOWLIST
    assert records[0].previous_status == OutboxEvent.STATUS_DEAD_LETTER
    assert records[0].previous_dead_letter_reason == "permanent_error"
    assert records[0].organization_id == organization_id

    # The handler is registered in this test, so the replayed event runs and is delivered.
    _set_handler(lambda _db, event: work_handler.append(str(event.id)))
    # Replay makes the event due at the wall clock, so the dispatch uses it too.
    assert _dispatch("worker-a", now=datetime.now(UTC) + timedelta(minutes=1)).delivered == 1
    assert work_handler == [str(event_id)]


def test_a_second_replay_changes_nothing(organization_id, work_handler) -> None:
    event_id = _dead_letter(organization_id)
    assert _replay(event_id, organization_id).replayed is True
    second = _replay(event_id, organization_id)
    assert second.replayed is False
    assert "not dead-lettered" in second.message
    with SessionLocal() as db:
        count = len(list(db.scalars(select(OutboxReplayRecord).where(OutboxReplayRecord.event_id == event_id))))
    assert count == 1


def test_replay_is_refused_when_this_process_has_no_handler(organization_id, work_handler) -> None:
    event_id = _dead_letter(organization_id)
    unregister_handler(WORK_EVENT_TYPE)
    with pytest.raises(ReplayError, match="No handler for this event type is registered"):
        _replay(event_id, organization_id)
    assert _stored(event_id).status == OutboxEvent.STATUS_DEAD_LETTER


def test_replay_rejects_a_reason_that_is_too_short(organization_id, work_handler) -> None:
    event_id = _dead_letter(organization_id)
    with pytest.raises(ReplayError, match="reason"):
        _replay(event_id, organization_id, reason="short")


def test_reporting_shows_the_dead_letter_reason(organization_id, work_handler) -> None:
    event_id = _dead_letter(organization_id, reason="no_administrator")
    with SessionLocal() as db:
        event = db.get(OutboxEvent, event_id)
        line = reporting._format_row(event)
    assert "reason=no_administrator" in line


# Usage alerts: state moves only on delivery -----------------------------------------


def _owner_into(organization_id: UUID) -> None:
    """Make a new user the system Owner of an existing organization (an administrator)."""
    from app.team.service import provision_default_organization_roles

    with TestingSessionLocal() as db:
        organization = db.get(Organization, organization_id)
        user = create_user(db)
        membership = create_membership(db, user=user, organization=organization)
        owner_role = provision_default_organization_roles(db, organization_id=organization.id)
        attach_role(db, membership=membership, role=owner_role)
        db.commit()


def _budget_alert_state(organization_id: UUID) -> int:
    with SessionLocal() as db:
        budget = db.scalar(select(OrganizationUsageBudget).where(
            OrganizationUsageBudget.organization_id == organization_id))
        return budget.last_alert_percent


def test_alert_state_advances_only_after_a_successful_delivery(organization_id) -> None:
    register_governance_handlers()
    try:
        with SessionLocal() as db:
            configure_budget(db, organization_id=organization_id, unit=UsageUnit.TOKENS_OUTPUT,
                             limit_quantity=100, moment=NOW)
            reserve(db, organization_id=organization_id, unit=UsageUnit.TOKENS_OUTPUT, quantity=70,
                    idempotency_key="ws3-alert-trigger", occurred_at=NOW)
            db.commit()
        # Enqueued but not delivered: the state must not advance.
        assert _budget_alert_state(organization_id) == 0

        result = _dispatch("alert-worker", now=datetime.now(UTC) + timedelta(minutes=5))
        assert result.dead_lettered == 1
        assert _budget_alert_state(organization_id) == 0
        with SessionLocal() as db:
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
        assert event.dead_letter_reason == REASON_NO_ADMINISTRATOR

        # An administrator is added, and the operator replays the dead letter.
        _owner_into(organization_id)
        outcome = _replay(event.id, organization_id, reason="Administrator added to organization")
        assert outcome.replayed is True
        result = _dispatch("alert-worker", now=datetime.now(UTC) + timedelta(hours=1))
        assert result.delivered == 1
        assert _budget_alert_state(organization_id) == 70
        with SessionLocal() as db:
            alerts = list(db.scalars(select(Notification).where(
                Notification.organization_id == organization_id,
                Notification.event_type == ALERT_NOTIFICATION_EVENT_TYPE,
            )))
        assert len(alerts) == 1
    finally:
        unregister_handler(THRESHOLD_EVENT_TYPE)


# Runtime: logs, supervision, health and the API boundary ------------------------------


def test_structured_logs_carry_identifiers_but_never_payloads_or_exception_text() -> None:
    record = logging.LogRecord("dealflow.worker", logging.WARNING, __file__, 1,
                               "Outbox event dispatch failed", None, None)
    record.outbox_event_id = "evt-1"
    record.outcome = "retried"
    record.error_type = "ValueError"
    try:
        raise ValueError("SECRET-PAYLOAD-VALUE in the message")
    except ValueError:
        record.exc_info = sys.exc_info()

    line = JsonLogFormatter().format(record)

    assert "SECRET-PAYLOAD-VALUE" not in line
    parsed = json.loads(line)
    assert parsed["outbox_event_id"] == "evt-1"
    assert parsed["outcome"] == "retried"
    assert parsed["exception_type"] == "ValueError"
    assert parsed["message"] == "Outbox event dispatch failed"


def test_a_loop_that_keeps_failing_stops_the_process_instead_of_spinning() -> None:
    stop = threading.Event()
    health = WorkerHealth(stale_seconds=60, loops=("outbox",))
    calls = 0

    def failing_cycle() -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("database unavailable")

    _run_loop(
        "outbox",
        worker_id="test",
        stop=stop,
        health=health,
        poll_seconds=0.001,
        max_consecutive_errors=3,
        cycle=failing_cycle,
    )

    assert calls == 3
    assert stop.is_set()
    assert health.fatal is not None
    assert "outbox loop failed" in health.fatal


def test_liveness_fails_for_a_stale_or_stopped_loop() -> None:
    health = WorkerHealth(stale_seconds=0.05, loops=("outbox", "email"))
    health.record_ok("outbox")
    health.record_ok("email")
    healthy, _ = health.liveness({"outbox": True, "email": True})
    assert healthy is True

    time.sleep(0.1)
    healthy, checks = health.liveness({"outbox": True, "email": True})
    assert healthy is False
    assert checks["outbox"] == "stale"

    health.record_ok("outbox")
    health.record_ok("email")
    healthy, checks = health.liveness({"outbox": True, "email": False})
    assert healthy is False
    assert checks["email"] == "stopped"


def test_probe_endpoints_report_status_over_http() -> None:
    register_governance_handlers()
    health = WorkerHealth(stale_seconds=60, loops=("outbox", "email"))
    health.record_ok("outbox")
    health.record_ok("email")
    server = _ProbeServer(("127.0.0.1", 0), health, lambda: {"outbox": True, "email": True})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/livez", timeout=10) as response:
            assert response.status == 200
            assert json.loads(response.read())["status"] == "live"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=10) as response:
            body = json.loads(response.read())
            assert response.status == 200
            assert body["checks"]["database"] == "ok"
            assert body["checks"]["handlers"] == "ok"

        health.fail("outbox loop failed 10 cycles in a row")
        with pytest.raises(urllib.error.HTTPError) as unhealthy:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/livez", timeout=10)
        assert unhealthy.value.code == 503
        with pytest.raises(urllib.error.HTTPError) as not_found:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/other", timeout=10)
        assert not_found.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_api_process_no_longer_starts_an_email_worker_thread() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        names = [thread.name for thread in threading.enumerate()]
    assert not any("email-outbox" in name for name in names)
    assert "worker-email" not in names


def test_serve_returns_zero_after_a_stop_request() -> None:
    from app.outbox.runtime import serve

    stop = threading.Event()
    result: dict[str, int] = {}

    def run() -> None:
        result["code"] = serve(
            worker_id="serve-test", probe_port=0, install_signal_handlers=False, stop_event=stop
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(1.0)
    stop.set()
    thread.join(timeout=60)

    assert not thread.is_alive()
    assert result["code"] == 0


def test_registered_handler_types_are_visible_to_readiness(work_handler) -> None:
    assert WORK_EVENT_TYPE in registered_event_types()
