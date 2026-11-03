"""Operating runtime for the dedicated DealFlow background worker (WS3, ADR-0026).

``python -m app.outbox.worker --serve`` runs this process. It is separate from the API process
and runs two supervised loops in threads:

* the transactional outbox dispatcher (``app.outbox.service``), and
* the encrypted email outbox (``app.auth.email_outbox_worker``).

Each loop records a heartbeat after every cycle. Liveness fails when a loop stops heartbeating
or a loop has failed too many times in a row, so the orchestrator can restart the process.
Readiness also checks the database and the registered handlers.

Shutdown is cooperative. SIGINT or SIGTERM sets a stop event. The dispatcher finishes the event
it is running and returns the rest of its batch to the queue without a failed attempt. An
email send in progress completes before its loop exits. The process exits 0 after a clean
stop and 1 after a fatal loop failure or when a loop does not stop within the grace period.

Logs are one JSON object per line. They carry identifiers, outcomes and error type names only.
Payloads, recipients, tokens and error messages are never logged.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import FrameType
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app.auth.email_outbox_worker import process_one_email
from app.config import get_settings
from app.db.session import SessionLocal
from app.governance.usage_ledger import expire_stale_reservations
from app.outbox.service import dispatch_due_events, registered_event_types
from app.providers.service import schedule_due_verifications

logger = logging.getLogger("dealflow.worker")

LOOP_OUTBOX = "outbox"
LOOP_EMAIL = "email"
_STRUCTURED_FIELDS = (
    "worker_id",
    "loop",
    "outbox_event_id",
    "event_type",
    "organization_id",
    "correlation_id",
    "attempt",
    "outcome",
    "dead_letter_reason",
    "error_type",
    "consecutive_errors",
    "claimed",
    "delivered",
    "retried",
    "dead_lettered",
    "lease_lost",
    "released",
    "signal",
    "reason",
)
MAX_BACKOFF_SECONDS = 60.0


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line. Only whitelisted structured fields are copied from the record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info and record.exc_info[0] is not None:
            # The exception message can contain data from a payload, so only the type is kept.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_worker_logging() -> None:
    """Send all logs of this process to stderr as JSON lines."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def default_worker_id() -> str:
    """Return a worker identity that is unique per process and bounded in length."""
    host = socket.gethostname().replace(" ", "-")[:40]
    return f"{host}:{os.getpid()}:{uuid4().hex[:8]}"[:120]


class WorkerHealth:
    """Heartbeats and failure state shared by the loops and the probe server."""

    def __init__(self, *, stale_seconds: float, loops: tuple[str, ...]) -> None:
        self._stale_seconds = stale_seconds
        self._loops = loops
        self._lock = threading.Lock()
        now = time.monotonic()
        self._last_ok = dict.fromkeys(loops, now)
        self._fatal: str | None = None

    def record_ok(self, loop: str) -> None:
        with self._lock:
            self._last_ok[loop] = time.monotonic()

    def fail(self, reason: str) -> None:
        with self._lock:
            if self._fatal is None:
                self._fatal = reason

    @property
    def fatal(self) -> str | None:
        with self._lock:
            return self._fatal

    def liveness(self, alive: dict[str, bool]) -> tuple[bool, dict[str, str]]:
        """Return whether the process is live, and a status for each loop."""
        now = time.monotonic()
        checks: dict[str, str] = {}
        with self._lock:
            fatal = self._fatal
            for loop in self._loops:
                if not alive.get(loop, False):
                    checks[loop] = "stopped"
                elif now - self._last_ok[loop] > self._stale_seconds:
                    checks[loop] = "stale"
                else:
                    checks[loop] = "ok"
        healthy = fatal is None and all(value == "ok" for value in checks.values())
        if fatal is not None:
            checks["process"] = "failed"
        return healthy, checks


def _database_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            db.rollback()
    except Exception:  # noqa: BLE001 - any failure means not ready; the type is not reported
        return False
    return True


class _ProbeRequestHandler(BaseHTTPRequestHandler):
    """Serves /livez and /readyz. Responses contain only status words, never tenant data."""

    server: _ProbeServer

    def do_GET(self) -> None:
        alive = self.server.alive()
        healthy, checks = self.server.health.liveness(alive)
        if self.path == "/livez":
            status = 200 if healthy else 503
            body: dict[str, object] = {"status": "live" if healthy else "unhealthy", "checks": checks}
        elif self.path == "/readyz":
            database_ok = healthy and _database_reachable()
            handlers_ok = bool(registered_event_types())
            ready = healthy and database_ok and handlers_ok
            status = 200 if ready else 503
            checks = {
                **checks,
                "database": "ok" if database_ok else "unavailable",
                "handlers": "ok" if handlers_ok else "none_registered",
            }
            body = {"status": "ready" if ready else "not_ready", "checks": checks}
        else:
            self.send_error(404)
            return
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        """Request lines are not logged, so probe traffic cannot leak paths or client data."""


class _ProbeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], health: WorkerHealth, alive: Any) -> None:
        super().__init__(address, _ProbeRequestHandler)
        self.health = health
        self.alive = alive


def _run_loop(
    name: str,
    *,
    worker_id: str,
    stop: threading.Event,
    health: WorkerHealth,
    poll_seconds: float,
    max_consecutive_errors: int,
    cycle: Any,
) -> None:
    consecutive_errors = 0
    while not stop.is_set():
        try:
            busy = cycle()
        except Exception as exc:  # noqa: BLE001 - supervision: any cycle failure is counted
            consecutive_errors += 1
            logger.error(
                "Worker loop cycle failed",
                extra={
                    "worker_id": worker_id,
                    "loop": name,
                    "outcome": "loop_error",
                    "error_type": type(exc).__name__,
                    "consecutive_errors": consecutive_errors,
                },
            )
            if consecutive_errors >= max_consecutive_errors:
                health.fail(f"{name} loop failed {consecutive_errors} cycles in a row")
                logger.error(
                    "Worker loop stopping the process after repeated failures",
                    extra={"worker_id": worker_id, "loop": name, "outcome": "fatal"},
                )
                stop.set()
                return
            stop.wait(min(poll_seconds * (2 ** min(consecutive_errors, 6)), MAX_BACKOFF_SECONDS))
            continue

        consecutive_errors = 0
        health.record_ok(name)
        if not busy:
            stop.wait(poll_seconds)


def _outbox_cycle(worker_id: str, stop: threading.Event) -> bool:
    # Due provider checks are queued here, in the worker, and never on an API request (ADR-0032).
    with SessionLocal() as db:
        schedule_due_verifications(db, now=datetime.now(UTC))
        db.commit()
    # Open AI usage reservations past their expiry are released here. Bounded per cycle (WS6 WP1).
    with SessionLocal() as db:
        reaped = expire_stale_reservations(db)
        db.commit()
    if reaped.expired or reaped.skipped:
        logger.info(
            "Usage reservation reaper finished",
            extra={
                "worker_id": worker_id,
                "expired": reaped.expired,
                "skipped": reaped.skipped,
            },
        )
    with SessionLocal() as db:
        result = dispatch_due_events(db, worker_id=worker_id, should_stop=stop.is_set)
    if result.claimed:
        logger.info(
            "Outbox dispatch cycle finished",
            extra={
                "worker_id": worker_id,
                "loop": LOOP_OUTBOX,
                "claimed": result.claimed,
                "delivered": result.delivered,
                "retried": result.retried,
                "dead_lettered": result.dead_lettered,
                "lease_lost": result.lease_lost,
                "released": result.released,
            },
        )
    return result.claimed > 0


def _email_cycle(worker_id: str, stop: threading.Event) -> bool:
    del worker_id, stop  # The email job is one bounded send; it runs to completion before the stop check.
    return process_one_email()


def serve(
    *,
    worker_id: str | None = None,
    probe_host: str | None = None,
    probe_port: int | None = None,
    install_signal_handlers: bool = True,
    stop_event: threading.Event | None = None,
) -> int:
    """Run the worker until a stop signal or a fatal failure. Return the process exit code."""
    settings = get_settings()
    identity = worker_id or default_worker_id()
    host = probe_host or settings.outbox_worker_probe_host
    port = settings.outbox_worker_probe_port if probe_port is None else probe_port

    from app.governance.alert_delivery import register_governance_handlers
    from app.providers.verification import register_provider_handlers

    register_governance_handlers()
    register_provider_handlers()
    configure_worker_logging()

    stop = stop_event or threading.Event()
    health = WorkerHealth(
        stale_seconds=settings.outbox_worker_stale_seconds,
        loops=(LOOP_OUTBOX, LOOP_EMAIL),
    )
    threads: dict[str, threading.Thread] = {}

    def alive() -> dict[str, bool]:
        return {name: thread.is_alive() for name, thread in threads.items()}

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Stop requested", extra={"worker_id": identity, "signal": signal.Signals(signum).name})
        stop.set()

    if install_signal_handlers:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

    probe = _ProbeServer((host, port), health, alive)
    probe_thread = threading.Thread(target=probe.serve_forever, name="worker-probes", daemon=True)
    probe_thread.start()

    loops = {
        LOOP_OUTBOX: lambda: _outbox_cycle(identity, stop),
        LOOP_EMAIL: lambda: _email_cycle(identity, stop),
    }
    polls = {
        LOOP_OUTBOX: settings.outbox_poll_seconds,
        LOOP_EMAIL: settings.email_outbox_poll_seconds,
    }
    for name, cycle in loops.items():
        thread = threading.Thread(
            target=_run_loop,
            name=f"worker-{name}",
            kwargs={
                "name": name,
                "worker_id": identity,
                "stop": stop,
                "health": health,
                "poll_seconds": polls[name],
                "max_consecutive_errors": settings.outbox_worker_max_consecutive_errors,
                "cycle": cycle,
            },
        )
        threads[name] = thread
        thread.start()

    logger.info(
        "Worker started",
        extra={"worker_id": identity, "outcome": "started"},
    )
    while not stop.is_set():
        stop.wait(1.0)

    deadline = time.monotonic() + settings.outbox_worker_shutdown_grace_seconds
    for thread in threads.values():
        thread.join(max(0.0, deadline - time.monotonic()))
    still_running = [name for name, thread in threads.items() if thread.is_alive()]

    probe.shutdown()
    probe.server_close()

    fatal = health.fatal
    if fatal is not None or still_running:
        logger.error(
            "Worker stopped with errors",
            extra={
                "worker_id": identity,
                "outcome": "failed",
                "reason": fatal or f"loops did not stop: {', '.join(still_running)}",
            },
        )
        return 1
    logger.info("Worker stopped", extra={"worker_id": identity, "outcome": "stopped"})
    return 0
