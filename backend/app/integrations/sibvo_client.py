"""Typed client for SIBVO's Dealsflo-facing endpoints.

SIBVO is the authority for identity, access, seats and entitlements. This
module is the only place Dealsflo calls those endpoints. Every call goes through
one request path that applies:

- a timeout on every request;
- a bounded retry (MAX_ATTEMPTS) for connection failures, timeouts and 5xx
  responses. Only idempotent operations are retried. Writes are safe to retry
  because SIBVO records their state and an idempotency key;
- a circuit breaker that stops calls after repeated SIBVO unavailability and
  probes again after a cooldown;
- normalized errors: `SibvoUnavailable`, `SibvoRejected`, `SibvoInvalidResponse`
  and `SibvoRequestDenied`;
- one correlation ID per operation and a structured trace line per attempt.

Logs carry operation names, attempt numbers, status codes and timings only.
They never carry secrets, tokens, subjects, emails or session identifiers.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
BREAKER_FAILURE_THRESHOLD = 5
BREAKER_COOLDOWN_SECONDS = 30.0


class SibvoError(Exception):
    """Base class for failures talking to SIBVO."""


class SibvoUnavailable(SibvoError):
    """SIBVO did not answer, failed server-side, or its circuit is open."""


class SibvoRejected(SibvoError):
    """SIBVO refused Dealsflo's client credentials. This is a configuration fault."""


class SibvoInvalidResponse(SibvoError):
    """SIBVO answered with a body that does not match the contract."""


class SibvoRequestDenied(SibvoError):
    """SIBVO refused a specific request. `error_code` is stable and safe to show."""

    def __init__(self, status_code: int, error_code: str | None) -> None:
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(f"SIBVO denied the request ({status_code}, {error_code}).")


CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Stops calling SIBVO after repeated unavailability, then probes once per cooldown.

    States: closed (calls flow), open (calls refused until the cooldown ends), half_open
    (one trial call is allowed; success closes the circuit, failure re-opens it).
    State is process-local. See docs/architecture/sibvo-dealsflo-entitlement-contract.md.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = BREAKER_FAILURE_THRESHOLD,
        cooldown_seconds: float = BREAKER_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state: CircuitState = "closed"
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False
        self._last_transition_at: str | None = None
        self._last_failure_category: str | None = None

    def _transition(self, new_state: CircuitState) -> None:
        if new_state != self._state:
            self._state = new_state
            self._last_transition_at = datetime.now(UTC).isoformat()

    def _cooldown_elapsed(self) -> bool:
        return self._opened_at is not None and self._clock() - self._opened_at >= self._cooldown_seconds

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == "open" and self._cooldown_elapsed():
                return "half_open"
            return self._state

    def before_call(self) -> None:
        """Raise when the circuit refuses calls. Admit exactly one trial when half-open."""
        with self._lock:
            if self._state == "closed":
                return
            if self._state == "open":
                if not self._cooldown_elapsed():
                    raise SibvoUnavailable("SIBVO calls are temporarily suspended.")
                self._transition("half_open")
            if self._trial_in_flight:
                raise SibvoUnavailable("SIBVO calls are temporarily suspended.")
            self._trial_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_in_flight = False
            self._transition("closed")

    def record_failure(self, category: str = "unreachable") -> None:
        with self._lock:
            self._last_failure_category = category
            self._trial_in_flight = False
            if self._state == "half_open":
                self._opened_at = self._clock()
                self._transition("open")
                return
            self._failures += 1
            if self._failures >= self._failure_threshold and self._state == "closed":
                self._opened_at = self._clock()
                self._transition("open")

    def reset(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = None
            self._trial_in_flight = False
            self._last_transition_at = None
            self._last_failure_category = None

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic view. Contains no credentials, tenant data or request content."""
        with self._lock:
            state = self._state
            if state == "open" and self._cooldown_elapsed():
                state = "half_open"
            remaining = None
            if self._state == "open" and self._opened_at is not None:
                remaining = max(0.0, round(self._cooldown_seconds - (self._clock() - self._opened_at), 1))
            return {
                "state": state,
                "failure_count": self._failures,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown_seconds,
                "cooldown_remaining_seconds": remaining,
                "last_transition_at": self._last_transition_at,
                "last_failure_category": self._last_failure_category,
                "recovered": state == "closed" and self._last_transition_at is not None,
            }


def _breaker_from_settings() -> CircuitBreaker:
    settings = get_settings()
    return CircuitBreaker(
        failure_threshold=settings.sibvo_circuit_failure_threshold,
        cooldown_seconds=settings.sibvo_circuit_cooldown_seconds,
    )


breaker = _breaker_from_settings()


@dataclass(frozen=True)
class SibvoSeatUsage:
    """Seat capacity SIBVO reports for the Dealsflo product."""

    organization_id: UUID
    product_key: str
    seat_limit: int | None
    allocated: int
    reserved: int
    available: int | None


@dataclass(frozen=True)
class SibvoSeatRelease:
    """SIBVO's answer to a removal-time seat release."""

    released: bool
    already_released: bool
    reason: str


@dataclass(frozen=True)
class SibvoHealth:
    """Health of the SIBVO dependency as seen from Dealsflo."""

    status: Literal["ready", "unavailable"]
    circuit: Literal["closed", "open", "half_open"]


def _credentials(settings: Settings) -> tuple[str, str]:
    secret = settings.sso_dealsflo_client_secret
    if secret is None or not secret.get_secret_value().strip():
        raise SibvoUnavailable("SIBVO client credentials are not configured.")
    return settings.sso_dealsflo_client_id, secret.get_secret_value()


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise SibvoInvalidResponse("SIBVO returned a malformed body.") from None
    if not isinstance(body, dict):
        raise SibvoInvalidResponse("SIBVO returned a non-object body.")
    return body


def _send(
    settings: Settings,
    *,
    operation: str,
    path: str,
    data: dict[str, str],
    retry_safe: bool,
) -> dict[str, Any]:
    """Send one form request through the breaker, with bounded retry and tracing.

    `retry_safe` is False for operations that must not be repeated. Such
    operations get exactly one attempt.
    """
    client_id, secret = _credentials(settings)
    url = settings.sso_sibvo_base_url.rstrip("/") + path
    correlation_id = str(uuid.uuid4())
    attempts = MAX_ATTEMPTS if retry_safe else 1

    for attempt in range(1, attempts + 1):
        breaker.before_call()
        started = time.monotonic()
        last_attempt = attempt == attempts
        try:
            with httpx.Client(timeout=settings.sso_http_timeout_seconds, follow_redirects=False) as client:
                response = client.post(
                    url,
                    data=data,
                    auth=(client_id, secret),
                    headers={"X-Correlation-ID": correlation_id},
                )
        except (httpx.TimeoutException, httpx.ConnectError) as error:
            category = "timeout" if isinstance(error, httpx.TimeoutException) else "unreachable"
            breaker.record_failure(category)
            _trace(operation, correlation_id, attempt, category, started)
            if last_attempt:
                raise SibvoUnavailable("SIBVO could not be reached.") from None
            continue
        except httpx.HTTPError:
            breaker.record_failure("http_error")
            _trace(operation, correlation_id, attempt, "http_error", started)
            raise SibvoUnavailable("SIBVO call failed.") from None

        status_code = response.status_code
        if status_code == 401:
            # SIBVO answered, so the dependency is reachable. The credentials are wrong.
            breaker.record_success()
            _trace(operation, correlation_id, attempt, "rejected", started, status_code)
            raise SibvoRejected("SIBVO rejected Dealsflo client credentials.")
        if status_code >= 500:
            breaker.record_failure("server_error")
            _trace(operation, correlation_id, attempt, "server_error", started, status_code)
            if last_attempt:
                raise SibvoUnavailable("SIBVO failed to answer.")
            continue

        breaker.record_success()
        if status_code >= 400:
            _trace(operation, correlation_id, attempt, "denied", started, status_code)
            error_code = None
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("error_code"), str):
                    error_code = body["error_code"]
            except ValueError:
                pass
            raise SibvoRequestDenied(status_code, error_code)

        body = _json_object(response)
        _trace(operation, correlation_id, attempt, "ok", started, status_code)
        return body

    raise SibvoUnavailable("SIBVO failed to answer.")


def _trace(
    operation: str,
    correlation_id: str,
    attempt: int,
    outcome: str,
    started: float,
    status_code: int | None = None,
) -> None:
    logger.info(
        "sibvo_call",
        extra={
            "sibvo_operation": operation,
            "correlation_id": correlation_id,
            "attempt": attempt,
            "outcome": outcome,
            "status_code": status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        },
    )


def _count(body: dict[str, Any], name: str) -> int:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SibvoInvalidResponse(f"Seat field {name} is invalid.")
    return value


def _optional_count(body: dict[str, Any], name: str) -> int | None:
    value = body.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SibvoInvalidResponse(f"Seat field {name} is invalid.")
    return value


def _check_binding(body: dict[str, Any], *, organization_id: UUID, product_key: str) -> None:
    if body.get("organization_id") != str(organization_id):
        raise SibvoInvalidResponse("Response is not bound to this organization.")
    if body.get("product_key") != product_key:
        raise SibvoInvalidResponse("Response is not bound to this product.")


def fetch_introspection(
    settings: Settings,
    *,
    subject: UUID,
    session_id: UUID,
    organization_id: UUID,
) -> dict[str, Any]:
    """Return SIBVO's raw introspection body for a session. Callers validate it."""
    return _send(
        settings,
        operation="introspect",
        path="/sso/introspect",
        data={
            "subject": str(subject),
            "session_id": str(session_id),
            "organization_id": str(organization_id),
        },
        retry_safe=True,
    )


def fetch_seat_usage(
    settings: Settings,
    *,
    subject: UUID,
    session_id: UUID,
    organization_id: UUID,
) -> SibvoSeatUsage | None:
    """Return SIBVO's seat usage for an attested session, or None when SIBVO denies it."""
    body = _send(
        settings,
        operation="seat_usage",
        path="/sso/seat-usage",
        data={
            "subject": str(subject),
            "session_id": str(session_id),
            "organization_id": str(organization_id),
        },
        retry_safe=True,
    )
    if body.get("active") is not True:
        return None
    _check_binding(body, organization_id=organization_id, product_key=settings.sso_dealsflo_product_key)
    seat_limit = _optional_count(body, "seat_limit")
    available = _optional_count(body, "available")
    return SibvoSeatUsage(
        organization_id=organization_id,
        product_key=settings.sso_dealsflo_product_key,
        seat_limit=seat_limit,
        allocated=_count(body, "allocated"),
        reserved=_count(body, "reserved"),
        available=available,
    )


def release_product_seat(
    settings: Settings,
    *,
    actor_subject: UUID,
    actor_session_id: UUID,
    organization_id: UUID,
    target_subject: UUID,
    reason: str,
    idempotency_key: str,
) -> SibvoSeatRelease:
    """Revoke a member's Dealsflo product membership in SIBVO and release the seat.

    Safe to retry: SIBVO reports an already released seat as `already_released`.
    Raises SibvoRequestDenied when SIBVO refuses, and SibvoUnavailable when the
    outcome is unknown. Callers must not report success on either.
    """
    body = _send(
        settings,
        operation="seat_release",
        path="/sso/product-seats/release",
        data={
            "subject": str(actor_subject),
            "session_id": str(actor_session_id),
            "organization_id": str(organization_id),
            "target_subject": str(target_subject),
            "reason": reason[:500],
            "idempotency_key": idempotency_key,
        },
        retry_safe=False,
    )
    released = body.get("released")
    already = body.get("already_released", False)
    reason_value = body.get("reason")
    if not isinstance(released, bool) or not isinstance(already, bool) or not isinstance(reason_value, str):
        raise SibvoInvalidResponse("SIBVO returned an invalid release result.")
    return SibvoSeatRelease(released=released, already_released=already, reason=reason_value)


def check_health(settings: Settings) -> SibvoHealth:
    """Probe SIBVO's readiness endpoint once. Used by operators, never by request paths."""
    url = settings.sso_sibvo_base_url.rstrip("/") + "/ready"
    try:
        with httpx.Client(timeout=settings.sso_http_timeout_seconds, follow_redirects=False) as client:
            response = client.get(url)
    except httpx.HTTPError:
        return SibvoHealth(status="unavailable", circuit=breaker.state)
    ready = False
    if response.status_code == 200:
        try:
            ready = response.json().get("status") == "ready"
        except ValueError:
            ready = False
    return SibvoHealth(status="ready" if ready else "unavailable", circuit=breaker.state)
