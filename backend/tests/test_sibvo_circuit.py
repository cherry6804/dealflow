"""SIBVO circuit breaker: state transitions, failure categories, diagnostics and safety."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings
from app.integrations import sibvo_client
from app.integrations.sibvo_client import (
    CircuitBreaker,
    SibvoUnavailable,
    release_product_seat,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


def make(threshold: int = 3, cooldown: float = 30.0) -> tuple[CircuitBreaker, FakeClock]:
    clock = FakeClock()
    return CircuitBreaker(failure_threshold=threshold, cooldown_seconds=cooldown, clock=clock), clock


def fail(breaker: CircuitBreaker, category: str = "unreachable") -> None:
    breaker.before_call()
    breaker.record_failure(category)


def test_closed_until_the_threshold_then_open() -> None:
    breaker, _ = make(threshold=3)

    fail(breaker)
    fail(breaker)
    assert breaker.state == "closed"
    fail(breaker)

    assert breaker.state == "open"
    assert breaker.snapshot()["failure_count"] == 3


def test_open_refuses_calls_without_touching_sibvo() -> None:
    breaker, _ = make(threshold=1)
    fail(breaker)

    with pytest.raises(SibvoUnavailable, match="temporarily suspended"):
        breaker.before_call()


def test_half_open_admits_one_trial_after_the_cooldown() -> None:
    breaker, clock = make(threshold=1, cooldown=30)
    fail(breaker)
    clock.now += 31

    assert breaker.state == "half_open"
    breaker.before_call()  # the single trial
    with pytest.raises(SibvoUnavailable):
        breaker.before_call()  # a second caller is refused while the trial is in flight


def test_successful_trial_closes_the_circuit_and_records_recovery() -> None:
    breaker, clock = make(threshold=1, cooldown=30)
    fail(breaker)
    clock.now += 31
    breaker.before_call()
    breaker.record_success()

    snap = breaker.snapshot()
    assert snap["state"] == "closed"
    assert snap["recovered"] is True
    assert snap["failure_count"] == 0
    assert snap["last_transition_at"] is not None


def test_failed_trial_reopens_the_circuit_for_a_new_cooldown() -> None:
    breaker, clock = make(threshold=1, cooldown=30)
    fail(breaker)
    clock.now += 31
    breaker.before_call()
    breaker.record_failure("timeout")

    assert breaker.state == "open"
    assert breaker.snapshot()["last_failure_category"] == "timeout"
    clock.now += 10
    with pytest.raises(SibvoUnavailable):
        breaker.before_call()


def test_snapshot_reports_cooldown_remaining_and_failure_category() -> None:
    breaker, clock = make(threshold=1, cooldown=30)
    fail(breaker, "server_error")
    clock.now += 12

    snap = breaker.snapshot()
    assert snap["state"] == "open"
    assert snap["cooldown_remaining_seconds"] == 18.0
    assert snap["last_failure_category"] == "server_error"
    assert snap["failure_threshold"] == 1
    assert set(snap) == {
        "state",
        "failure_count",
        "failure_threshold",
        "cooldown_seconds",
        "cooldown_remaining_seconds",
        "last_transition_at",
        "last_failure_category",
        "recovered",
    }


def test_settings_build_the_breaker_threshold_and_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIBVO_CIRCUIT_FAILURE_THRESHOLD", "7")
    monkeypatch.setenv("SIBVO_CIRCUIT_COOLDOWN_SECONDS", "45")
    get_settings.cache_clear()
    try:
        built = sibvo_client._breaker_from_settings()
        assert built.snapshot()["failure_threshold"] == 7
        assert built.snapshot()["cooldown_seconds"] == 45
    finally:
        get_settings.cache_clear()


def test_diagnostics_cannot_be_enabled_in_production() -> None:
    with pytest.raises(ValidationError, match="circuit diagnostic"):
        Settings(_env_file=None, app_environment="production", sibvo_diagnostics_enabled=True)


@pytest.fixture
def diagnostics_client(monkeypatch: pytest.MonkeyPatch):
    from app.api import diagnostics
    from app.main import app

    fresh, _ = make(threshold=2)
    monkeypatch.setattr(sibvo_client, "breaker", fresh)
    enabled = get_settings().model_copy(update={"sibvo_diagnostics_enabled": True})
    monkeypatch.setattr(diagnostics, "get_settings", lambda: enabled)
    return app, fresh


def test_diagnostic_is_hidden_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import diagnostics
    from app.main import app

    disabled = get_settings().model_copy(update={"sibvo_diagnostics_enabled": False})
    monkeypatch.setattr(diagnostics, "get_settings", lambda: disabled)

    response = TestClient(app, client=("127.0.0.1", 50000)).get("/api/v1/diagnostics/sibvo-circuit")

    assert response.status_code == 404


def test_diagnostic_is_loopback_only(diagnostics_client) -> None:
    app, _ = diagnostics_client

    remote = TestClient(app, client=("203.0.113.9", 50000)).get("/api/v1/diagnostics/sibvo-circuit")

    assert remote.status_code == 403
    assert "token" not in remote.text.lower()


def test_diagnostic_reports_circuit_state_to_a_local_client(diagnostics_client) -> None:
    app, breaker = diagnostics_client
    fail(breaker)
    fail(breaker)

    response = TestClient(app, client=("127.0.0.1", 50000)).get("/api/v1/diagnostics/sibvo-circuit")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "open"
    assert body["failure_threshold"] == 2
    assert body["last_failure_category"] == "unreachable"
    assert not any(secret in response.text for secret in ("secret", "token", "password"))


def test_release_is_a_single_attempt_so_a_mutation_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh, _ = make(threshold=50)
    monkeypatch.setattr(sibvo_client, "breaker", fresh)
    calls: list[int] = []

    class CountingClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            calls.append(1)
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(sibvo_client.httpx, "Client", CountingClient)
    settings = get_settings().model_copy(update={"sso_dealsflo_client_secret": SecretStr("test-client-secret")})

    with pytest.raises(SibvoUnavailable):
        release_product_seat(
            settings,
            actor_subject=uuid.uuid4(),
            actor_session_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            target_subject=uuid.uuid4(),
            reason="retry safety",
            idempotency_key="circuit-test-0001",
        )
    assert calls == [1]
