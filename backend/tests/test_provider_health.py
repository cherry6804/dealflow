"""Provider health: stale-connection detection, readiness reporting and sweep isolation (ADR-0032).

Connections are created and verified through the real services and the real outbox handler, as in
``test_provider_connection_lifecycle``. Provider calls use the same stub boundary. No test contacts a provider.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.independent import OUTCOME_COMPLETED, AuditPersistenceError
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.provider_connection import ProviderConnection
from app.db.session import SessionLocal
from app.governance import policy as policy_module
from app.governance.capabilities import AI_MASTER
from app.governance.policy import evaluate_capability
from app.governance.service import set_capability_enabled
from app.outbox import runtime
from app.providers import health
from app.providers.base import VerificationOutcome
from app.providers.health import STALE_ACTION, detect_stale_connections
from app.providers.readiness import ReadinessCode, best_provider_readiness
from tests.governance_helpers import allow_organization_entitlements
from tests.test_provider_connection_lifecycle import (
    PROVIDER,
    StubAdapter,
    _cleanup,
    _connect,
    _result,
    _secret,
    _state,
    _use_adapter,
    _verify,
)
from tests.test_team_api import create_owner_manager


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


@pytest.fixture
def keyring(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "test-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"test-v1": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def org(keyring) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    user, organization = create_owner_manager(
        permissions=("provider_credentials.manage", "provider_credentials.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


def _stale_at(hours_beyond_freshness: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(hours=get_settings().provider_connection_freshness_hours + hours_beyond_freshness)


def _make_stale(connection_id: uuid.UUID, verified_at: datetime) -> None:
    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        assert row is not None
        row.last_verified_at = verified_at
        db.commit()


def _sweep() -> int:
    with SessionLocal() as db:
        examined = detect_stale_connections(db, now=datetime.now(UTC))
        db.commit()
        return examined


def _stale_rows(organization_id: uuid.UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == STALE_ACTION,
            )
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def test_a_stale_connection_is_recorded_once_for_the_episode(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    verified_at = _stale_at()
    _make_stale(connection_id, verified_at)

    assert _sweep() == 1
    assert _sweep() == 0  # A repeated sweep finds the episode already recorded and records nothing new.

    rows = _stale_rows(organization_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == OUTCOME_COMPLETED
    assert row.user_id is None
    assert row.resource_id == str(connection_id)
    assert row.event_type == "provider_connection"
    assert row.correlation_id


def test_stale_metadata_never_contains_the_secret(org, monkeypatch) -> None:
    organization_id, user_id = org
    secret = _secret()
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id, secret)
    _verify(organization_id)
    _make_stale(connection_id, _stale_at())
    _sweep()

    (row,) = _stale_rows(organization_id)
    assert secret not in (row.event_metadata or "")
    assert secret not in str(row.__dict__)


def test_a_healthy_connection_is_not_recorded(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    _connect(organization_id, user_id)
    _verify(organization_id)

    assert _sweep() == 0
    assert _stale_rows(organization_id) == []


def test_a_new_verification_starts_a_new_staleness_episode(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    _make_stale(connection_id, _stale_at(1))
    _sweep()

    _make_stale(connection_id, _stale_at(2))  # Verified again earlier, then stale again: a second episode.
    _sweep()

    assert len(_stale_rows(organization_id)) == 2


def test_repeated_sweeps_do_not_duplicate_the_episode_row(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    _make_stale(connection_id, _stale_at())

    # Several sweeps, as concurrent workers would run them, write against the same idempotency key.
    _sweep()
    _sweep()
    _sweep()

    assert len(_stale_rows(organization_id)) == 1


def test_a_failed_audit_write_does_not_stop_the_sweep_for_other_organizations(keyring, monkeypatch) -> None:
    user_a, org_a = create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    user_b, org_b = create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    try:
        _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
        for user, organization in ((user_a, org_a), (user_b, org_b)):
            connection_id = _connect(organization.id, user.id)
            _verify(organization.id)
            _make_stale(connection_id, _stale_at())

        real_persist = health.persist_idempotent_audit_event
        calls: list[int] = []

        def fail_first(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise AuditPersistenceError("The audit record could not be written.")
            return real_persist(*args, **kwargs)

        monkeypatch.setattr(health, "persist_idempotent_audit_event", fail_first)
        # Both episodes are attempted. The first write fails, so only the second is recorded.
        assert _sweep() == 1
        assert len(calls) == 2

        recorded = len(_stale_rows(org_a.id)) + len(_stale_rows(org_b.id))
        assert recorded == 1
        # The failed episode stays eligible, so the next sweep records it.
        assert _sweep() == 1
        assert len(_stale_rows(org_a.id)) + len(_stale_rows(org_b.id)) == 2
    finally:
        _cleanup(org_a.id)
        _cleanup(org_b.id)


def test_a_provider_sweep_failure_does_not_stop_reservation_expiry(monkeypatch) -> None:
    reaper_calls: list[int] = []

    def failing_schedule(*args, **kwargs):
        raise SQLAlchemyError("provider sweep unavailable")

    def recording_reaper(db, **kwargs):
        reaper_calls.append(1)
        return SimpleNamespace(expired=0, skipped=0)

    monkeypatch.setattr(runtime, "schedule_due_verifications", failing_schedule)
    monkeypatch.setattr(runtime, "expire_stale_reservations", recording_reaper)
    monkeypatch.setattr(runtime, "dispatch_due_events", lambda *args, **kwargs: SimpleNamespace(claimed=0))

    runtime._outbox_cycle("worker-test", threading.Event())

    assert reaper_calls == [1]


def test_the_policy_denial_says_why_the_provider_is_not_ready(org, monkeypatch) -> None:
    organization_id, user_id = org
    allow_organization_entitlements(monkeypatch)
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    with SessionLocal() as db:
        for key in (AI_MASTER, "ai.assistant"):
            set_capability_enabled(db, organization_id=organization_id, actor_user_id=user_id, capability_key=key, is_enabled=True)
        db.commit()

    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    _make_stale(connection_id, _stale_at())

    with SessionLocal() as db:
        decision = evaluate_capability(db, organization_id=organization_id, capability_key="ai.assistant")
        db.commit()
    assert decision.reason_code == policy_module.REASON_PROVIDER_NOT_CONNECTED
    assert decision.provider_readiness == ReadinessCode.STALE.value
    assert decision.as_dict()["provider_readiness"] == ReadinessCode.STALE.value


def test_a_capability_without_a_provider_has_no_readiness_field(org, monkeypatch) -> None:
    organization_id, _user_id = org
    allow_organization_entitlements(monkeypatch)
    with SessionLocal() as db:
        decision = evaluate_capability(db, organization_id=organization_id, capability_key=AI_MASTER)
        db.commit()
    assert decision.provider_readiness is None
    assert "provider_readiness" not in decision.as_dict()


def test_the_best_readiness_prefers_a_ready_provider_and_otherwise_the_most_useful_state(org, monkeypatch) -> None:
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))

    with SessionLocal() as db:
        empty = best_provider_readiness(db, organization_id=organization_id, provider_keys=())
        unknown = best_provider_readiness(db, organization_id=organization_id, provider_keys=("not-a-provider",))
    assert empty.code is ReadinessCode.NOT_CONNECTED
    assert unknown.code is ReadinessCode.NOT_CONNECTED

    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    with SessionLocal() as db:
        ready = best_provider_readiness(db, organization_id=organization_id, provider_keys=(PROVIDER, "not-a-provider"))
    assert ready.ready and ready.code is ReadinessCode.READY

    _make_stale(connection_id, _stale_at())
    with SessionLocal() as db:
        stale = best_provider_readiness(db, organization_id=organization_id, provider_keys=(PROVIDER, "not-a-provider"))
    assert not stale.ready and stale.code is ReadinessCode.STALE


def test_stale_detection_is_tenant_scoped(keyring, monkeypatch) -> None:
    user_a, org_a = create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    user_b, org_b = create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    try:
        _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
        stale_connection = _connect(org_a.id, user_a.id)
        _verify(org_a.id)
        _make_stale(stale_connection, _stale_at())
        _connect(org_b.id, user_b.id)
        _verify(org_b.id)

        _sweep()

        assert len(_stale_rows(org_a.id)) == 1
        assert _stale_rows(org_b.id) == []
        assert _state(stale_connection).organization_id == org_a.id
    finally:
        _cleanup(org_a.id)
        _cleanup(org_b.id)


def test_concurrent_sweeps_record_each_episode_once(org, monkeypatch) -> None:
    """Real threads, each with its own session, sweep the same stale connection at the same time."""
    from concurrent.futures import ThreadPoolExecutor

    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    _make_stale(connection_id, _stale_at())

    barrier = threading.Barrier(4)

    def sweep_together() -> int:
        barrier.wait()
        return _sweep()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: sweep_together(), range(4)))

    # Exactly one sweep wrote the episode. Each other sweep either saw it already recorded or lost the insert race and
    # counted nothing, so the sweeps together record one episode.
    assert sorted(results) == [0, 0, 0, 1]
    assert len(_stale_rows(organization_id)) == 1


def test_the_serve_cycle_schedules_and_runs_a_due_provider_check(org, monkeypatch) -> None:
    """The production worker cycle (``--serve``) queues a due check and dispatches it to the adapter.

    ``--once`` only dispatches queued events and does not run the sweep, so this test exercises the serve path.
    """
    from app.db.models.provider_verification_attempt import ProviderVerificationAttempt
    from app.providers.verification import register_provider_handlers

    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)

    # The next check is due now. A transient failure from the adapter must show up as a degraded connection.
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.TRANSIENT_FAILURE, "provider_unavailable")))
    with SessionLocal() as db:
        row = db.get(ProviderConnection, connection_id)
        row.next_verification_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    register_provider_handlers()
    runtime._outbox_cycle("serve-test", threading.Event())

    with SessionLocal() as db:
        attempts = db.scalars(
            select(ProviderVerificationAttempt).where(
                ProviderVerificationAttempt.organization_id == organization_id,
                ProviderVerificationAttempt.trigger == "scheduled",
            )
        ).all()
        assert len(attempts) >= 1
    assert _state(connection_id).status == ProviderConnection.STATUS_DEGRADED


def test_a_stale_provider_denies_execution_at_the_gate_boundary(monkeypatch, keyring) -> None:
    """``evaluate_execution`` is the only execution path. A stale provider stops it at the policy step.

    The actor belongs to the same organization as the connection, so the denial is caused by provider readiness and
    not by the actor gate. The send permission is a test-only grant (see ``test_channel_send_authorization``).
    """
    from app.governance import execution_gate
    from app.governance.execution_gate import ExecutionRequest, evaluate_execution
    from tests.governance_helpers import attested_user_context

    user, organization = create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read"))
    organization_id = organization.id
    try:
        allow_organization_entitlements(monkeypatch)
        _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
        monkeypatch.setattr(execution_gate, "DEFAULT_AI_PERMISSION", "governance.consent.read")
        with SessionLocal() as db:
            for key in (AI_MASTER, "ai.assistant"):
                set_capability_enabled(db, organization_id=organization_id, actor_user_id=user.id, capability_key=key, is_enabled=True)
            db.commit()

        connection_id = _connect(organization_id, user.id)
        _verify(organization_id)
        _make_stale(connection_id, _stale_at())

        request = ExecutionRequest(
            organization_id=organization_id,
            capability_key="ai.assistant",
            user_context=attested_user_context(user, organization_id=organization_id),
            resource_id=str(uuid.uuid4()),
        )
        with SessionLocal() as db:
            decision = evaluate_execution(db, request)
            db.commit()
        assert decision.allowed is False
        assert decision.reason_code == policy_module.REASON_PROVIDER_NOT_CONNECTED
    finally:
        _cleanup(organization_id)


def test_a_backlog_larger_than_the_sweep_limit_is_worked_through_over_sweeps(keyring, monkeypatch) -> None:
    """Three stale episodes with a limit of two: the first sweep records two, the next records the third.

    Without skipping recorded episodes, the first two would be re-read forever and the third never recorded.
    """
    organizations = [
        create_owner_manager(permissions=("provider_credentials.manage", "provider_credentials.read")) for _ in range(3)
    ]
    try:
        _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
        for user, organization in organizations:
            connection_id = _connect(organization.id, user.id)
            _verify(organization.id)
            _make_stale(connection_id, _stale_at())

        def sweep(limit: int) -> int:
            with SessionLocal() as db:
                recorded = detect_stale_connections(db, now=datetime.now(UTC), limit=limit)
                db.commit()
                return recorded

        assert sweep(2) == 2
        assert sweep(2) == 1
        assert sweep(2) == 0
        assert sum(len(_stale_rows(organization.id)) for _user, organization in organizations) == 3
    finally:
        for _user, organization in organizations:
            _cleanup(organization.id)



def test_a_sweep_that_loses_the_insert_race_counts_nothing(org, monkeypatch) -> None:
    """Deterministic version of the race: the episode looks unrecorded when the sweep checks, but the insert conflicts.

    The sweep must count zero for an episode it did not write.
    """
    organization_id, user_id = org
    _use_adapter(monkeypatch, StubAdapter(_result(VerificationOutcome.SUCCEEDED)))
    connection_id = _connect(organization_id, user_id)
    _verify(organization_id)
    _make_stale(connection_id, _stale_at())
    assert _sweep() == 1

    monkeypatch.setattr(health, "_already_recorded", lambda db, connection, verified_at: False)
    assert _sweep() == 0
    assert len(_stale_rows(organization_id)) == 1
