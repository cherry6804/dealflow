"""Execution rate limits per organization and actor (E13 hardening).

Covers boundaries, window recovery, tenant isolation, concurrent consumption, fail-closed behavior,
the structured response, no double counting against usage budgets, and the deal-created automation
integration. Time is injected so windows are deterministic.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.automation_rules.execution_service import execute_deal_created_automations
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.automation_execution import AutomationExecution
from app.db.models.deal import Deal
from app.db.models.execution_rate_limit_window import ExecutionRateLimitWindow
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.session import SessionLocal
from app.rate_limits import limiter as limiter_module
from app.rate_limits.limiter import (
    REASON_ALLOWED,
    REASON_RATE_LIMITED,
    REASON_UNAVAILABLE,
    consume,
    consume_or_deny,
)
from app.rate_limits.policy import (
    AUTOMATION_DEAL_CREATED_EXECUTION,
    RULES,
    RateLimitRule,
)
from app.rate_limits.responses import rate_limit_error_response
from tests.governance_helpers import attested_user_context
from tests.test_automation_execution_service import create_active_rule, create_test_deal
from tests.test_deals_api import create_authorized_user

NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
WINDOW = timedelta(seconds=60)
EXECUTION = AUTOMATION_DEAL_CREATED_EXECUTION


def _set_rule(monkeypatch, *, organization_limit: int, actor_limit: int) -> None:
    monkeypatch.setitem(
        RULES,
        EXECUTION,
        RateLimitRule(
            execution_type=EXECUTION,
            window=WINDOW,
            organization_limit=organization_limit,
            actor_limit=actor_limit,
        ),
    )


def _new_organization() -> tuple:
    with SessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=())
        db.commit()
        return user.id, organization.id


def _consume(organization_id, actor_id, *, now=NOW):
    with SessionLocal() as db:
        decision = consume(
            db,
            organization_id=organization_id,
            execution_type=EXECUTION,
            actor_user_id=actor_id,
            now=now,
        )
        db.commit()
        return decision


# --- boundaries and windows ----------------------------------------------------------------


def test_actor_limit_allows_exactly_the_limit_then_denies_with_retry_information(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=100, actor_limit=2)
    organization_id = _new_organization()[1]
    actor_id = uuid4()

    first = _consume(organization_id, actor_id)
    second = _consume(organization_id, actor_id)
    third = _consume(organization_id, actor_id)

    assert first.allowed and second.allowed
    # Remaining is the smaller headroom across scopes: min(100 - 1, 2 - 1).
    assert first.reason_code == REASON_ALLOWED and first.remaining == 1
    assert not third.allowed
    assert third.reason_code == REASON_RATE_LIMITED
    assert third.scope == "actor"
    assert third.limit == 2
    assert 1 <= third.retry_after_seconds <= 60


def test_organization_limit_applies_across_different_actors(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=2, actor_limit=10)
    organization_id = _new_organization()[1]

    decisions = [_consume(organization_id, uuid4()) for _ in range(3)]

    assert [d.allowed for d in decisions] == [True, True, False]
    assert decisions[2].scope == "organization"
    assert decisions[2].limit == 2


def test_window_expiry_restores_allowance(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=1, actor_limit=1)
    organization_id = _new_organization()[1]
    actor_id = uuid4()

    assert _consume(organization_id, actor_id, now=NOW).allowed
    assert not _consume(organization_id, actor_id, now=NOW + timedelta(seconds=30)).allowed
    recovered = _consume(organization_id, actor_id, now=NOW + timedelta(seconds=61))

    assert recovered.allowed


def test_denied_attempts_still_count_so_repeated_attempts_cannot_slip_through(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=100, actor_limit=2)
    organization_id = _new_organization()[1]
    actor_id = uuid4()

    for _ in range(5):
        _consume(organization_id, actor_id)

    with SessionLocal() as db:
        count = db.scalar(
            select(ExecutionRateLimitWindow.count).where(
                ExecutionRateLimitWindow.organization_id == organization_id,
                ExecutionRateLimitWindow.scope_type == "actor",
                ExecutionRateLimitWindow.scope_id == str(actor_id),
            )
        )
    assert count == 5


def test_tenants_have_independent_counters(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=1, actor_limit=10)
    org_a = _new_organization()[1]
    org_b = _new_organization()[1]

    assert _consume(org_a, uuid4()).allowed
    assert not _consume(org_a, uuid4()).allowed
    assert _consume(org_b, uuid4()).allowed


# --- concurrency ----------------------------------------------------------------------------


def test_concurrent_consumption_never_exceeds_the_limit(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=5, actor_limit=1000)
    organization_id = _new_organization()[1]

    def attempt(_: int) -> bool:
        return _consume(organization_id, None).allowed

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(40)))

    assert sum(results) == 5
    assert len(results) == 40


def test_concurrent_actor_consumption_never_exceeds_the_actor_limit(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=1000, actor_limit=3)
    organization_id = _new_organization()[1]
    actor_id = uuid4()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: _consume(organization_id, actor_id).allowed, range(24)))

    assert sum(results) == 3


# --- fail closed ----------------------------------------------------------------------------


def test_unavailable_store_denies_and_leaves_the_session_usable(monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise OperationalError("UPDATE execution_rate_limit_windows", {}, Exception("store unavailable"))

    monkeypatch.setattr(limiter_module, "_increment", broken)
    organization_id = _new_organization()[1]

    with SessionLocal() as db:
        decision = consume_or_deny(
            db,
            organization_id=organization_id,
            execution_type=EXECUTION,
            actor_user_id=uuid4(),
        )
        assert db.scalar(select(func.count()).select_from(AuditEvent)) is not None

    assert not decision.allowed
    assert decision.reason_code == REASON_UNAVAILABLE


def test_unknown_execution_type_fails_closed() -> None:
    organization_id = _new_organization()[1]

    with SessionLocal() as db:
        decision = consume_or_deny(
            db,
            organization_id=organization_id,
            execution_type="not.configured",
            actor_user_id=None,
        )

    assert not decision.allowed
    assert decision.reason_code == REASON_UNAVAILABLE


def test_rule_validation_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        RateLimitRule(execution_type="x", window=timedelta(0), organization_limit=1, actor_limit=1)
    with pytest.raises(ValueError):
        RateLimitRule(execution_type="x", window=WINDOW, organization_limit=0, actor_limit=1)


# --- structured response ---------------------------------------------------------------------


def test_rate_limited_response_is_429_with_retry_after_and_structured_body(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=100, actor_limit=1)
    organization_id = _new_organization()[1]
    actor_id = uuid4()
    _consume(organization_id, actor_id)
    denied = _consume(organization_id, actor_id)

    response = rate_limit_error_response(denied)
    body = json.loads(response.body)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(denied.retry_after_seconds)
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["details"]["scope"] == "actor"
    assert body["error"]["details"]["limit"] == 1
    assert body["error"]["details"]["retry_after_seconds"] == denied.retry_after_seconds


def test_unavailable_response_is_503_and_does_not_claim_a_limit_was_exceeded() -> None:
    from app.rate_limits.limiter import RateLimitDecision

    decision = RateLimitDecision(
        allowed=False,
        reason_code=REASON_UNAVAILABLE,
        execution_type=EXECUTION,
        scope=None,
        limit=None,
        remaining=0,
        retry_after_seconds=0,
    )
    response = rate_limit_error_response(decision)
    body = json.loads(response.body)

    assert response.status_code == 503
    assert body["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"


def test_allowed_decision_has_no_error_response(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=10, actor_limit=10)
    allowed = _consume(_new_organization()[1], uuid4())
    with pytest.raises(ValueError):
        rate_limit_error_response(allowed)


# --- no double counting ----------------------------------------------------------------------


def test_rate_limiting_writes_no_usage_or_budget_records(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=100, actor_limit=100)
    organization_id = _new_organization()[1]

    def usage_counts():
        with SessionLocal() as db:
            return (
                db.scalar(select(func.count()).select_from(AiUsageEvent)),
                db.scalar(select(func.count()).select_from(OrganizationUsageBudget)),
            )

    before = usage_counts()
    for _ in range(3):
        _consume(organization_id, uuid4())

    assert usage_counts() == before


# --- deal-created automation integration -----------------------------------------------------


def test_rate_limited_automation_creates_no_executions_and_keeps_the_deal(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=1000, actor_limit=1)

    with SessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=())
        rule = create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[{"type": "CREATE_FOLLOW_UP", "config": {"days_after": 1, "title": "Rate test"}}],
        )
        first_deal = create_test_deal(db, user=user, organization=organization)
        second_deal = create_test_deal(db, user=user, organization=organization)
        context = attested_user_context(user, organization_id=organization.id)

        first = execute_deal_created_automations(
            db, organization_id=organization.id, deal=first_deal, user_context=context,
        )
        second = execute_deal_created_automations(
            db, organization_id=organization.id, deal=second_deal, user_context=context,
        )
        db.flush()

        executions = db.scalar(
            select(func.count()).select_from(AutomationExecution).where(
                AutomationExecution.rule_id == rule.id,
            )
        )
        deal_still_exists = db.get(Deal, second_deal.id) is not None
        denial = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization.id,
                AuditEvent.action == "rate_limit.denied",
            )
        ).all()
        metadata = [json.loads(event.event_metadata) for event in denial]
        db.rollback()

    assert len(first) == 1
    assert second == []
    assert executions == 1
    assert deal_still_exists
    assert len(metadata) == 1
    assert metadata[0]["scope"] == "actor"
    assert metadata[0]["limit"] == 1
    assert "secret" not in json.dumps(metadata).lower()


def test_automation_fails_safely_when_the_limiter_is_unavailable(monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise OperationalError("UPDATE execution_rate_limit_windows", {}, Exception("store unavailable"))

    monkeypatch.setattr(limiter_module, "_increment", broken)

    with SessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=())
        rule = create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[{"type": "CREATE_FOLLOW_UP", "config": {"days_after": 1, "title": "Unavailable test"}}],
        )
        deal = create_test_deal(db, user=user, organization=organization)
        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
            user_context=attested_user_context(user, organization_id=organization.id),
        )
        db.flush()
        deal_exists = db.get(Deal, deal.id) is not None
        rule_executions = db.scalar(
            select(func.count()).select_from(AutomationExecution).where(
                AutomationExecution.rule_id == rule.id,
            )
        )
        db.rollback()

    assert executions == []
    assert deal_exists
    assert rule_executions == 0


def test_window_counter_table_is_tenant_scoped() -> None:
    organization_id = _new_organization()[1]
    _consume(organization_id, None)
    with SessionLocal() as db:
        rows = db.scalars(
            select(ExecutionRateLimitWindow).where(
                ExecutionRateLimitWindow.organization_id == organization_id,
            )
        ).all()
    assert rows
    assert all(row.organization_id == organization_id for row in rows)


def test_actor_counters_are_isolated_within_one_organization(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=100, actor_limit=1)
    organization_id = _new_organization()[1]
    actor_a, actor_b = uuid4(), uuid4()

    assert _consume(organization_id, actor_a).allowed
    assert not _consume(organization_id, actor_a).allowed
    assert _consume(organization_id, actor_b).allowed


def test_retry_after_counts_down_to_the_window_end(monkeypatch) -> None:
    _set_rule(monkeypatch, organization_limit=100, actor_limit=1)
    organization_id = _new_organization()[1]
    actor_id = uuid4()

    _consume(organization_id, actor_id, now=NOW)
    denied_later = _consume(organization_id, actor_id, now=NOW + timedelta(seconds=10))

    assert not denied_later.allowed
    assert denied_later.retry_after_seconds == 50


_MULTI_PROCESS_SCRIPT = """
import sys
from uuid import UUID
from datetime import datetime, UTC
from app.db.session import SessionLocal
from app.rate_limits.limiter import consume
from app.rate_limits.policy import RULES, RateLimitRule
org = UUID(sys.argv[1])
moment = datetime.fromisoformat(sys.argv[2])
execution = sys.argv[3]
# Each process is separate, so it must apply the same limit the test configured.
RULES[execution] = RateLimitRule(
    execution_type=execution,
    window=RULES[execution].window,
    organization_limit=int(sys.argv[4]),
    actor_limit=RULES[execution].actor_limit,
)
allowed = 0
for _ in range(10):
    with SessionLocal() as db:
        decision = consume(db, organization_id=org, execution_type=execution, actor_user_id=None, now=moment)
        db.commit()
        allowed += int(decision.allowed)
print(allowed)
"""


def test_counters_are_shared_across_separate_processes(monkeypatch) -> None:
    import os
    import subprocess
    import sys

    _set_rule(monkeypatch, organization_limit=15, actor_limit=1000)
    organization_id = _new_organization()[1]
    env = os.environ.copy()
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", _MULTI_PROCESS_SCRIPT, str(organization_id), NOW.isoformat(), EXECUTION, "15"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        for _ in range(4)
    ]
    outputs = [process.communicate(timeout=300) for process in processes]

    for process, (stdout, stderr) in zip(processes, outputs):
        assert process.returncode == 0, stderr
    total_allowed = sum(int(stdout.strip()) for stdout, _ in outputs)
    # Four processes each make ten attempts (forty in total) against a limit of fifteen.
    assert total_allowed == 15


def test_window_start_comes_from_the_database_clock(monkeypatch) -> None:
    from sqlalchemy import func as sql_func

    _set_rule(monkeypatch, organization_limit=100, actor_limit=100)
    organization_id = _new_organization()[1]
    with SessionLocal() as db:
        consume(db, organization_id=organization_id, execution_type=EXECUTION, actor_user_id=None)
        window_started = db.scalar(
            select(ExecutionRateLimitWindow.window_started_at).where(
                ExecutionRateLimitWindow.organization_id == organization_id,
            )
        )
        database_now = db.scalar(select(sql_func.now()))
        db.rollback()

    # Both values come from the same transaction clock, so they are identical.
    assert window_started == database_now


def test_a_window_as_long_as_retention_is_rejected() -> None:
    from app.rate_limits.policy import RETENTION

    with pytest.raises(ValueError):
        RateLimitRule(execution_type="x", window=RETENTION, organization_limit=1, actor_limit=1)


def test_unavailable_store_is_logged_without_sql_text(monkeypatch, caplog) -> None:
    def broken(*args, **kwargs):
        raise OperationalError("UPDATE secret_table SET count = 1", {"p": "hidden"}, Exception("store down"))

    monkeypatch.setattr(limiter_module, "_increment", broken)
    organization_id = _new_organization()[1]

    with caplog.at_level("ERROR", logger="app.rate_limits.limiter"), SessionLocal() as db:
        decision = consume_or_deny(
            db, organization_id=organization_id, execution_type=EXECUTION, actor_user_id=None,
        )

    assert not decision.allowed
    messages = [record.getMessage() for record in caplog.records if record.name == "app.rate_limits.limiter"]
    assert any("rate_limit_unavailable" in message for message in messages)
    assert all("secret_table" not in message and "hidden" not in message for message in messages)
