"""Command-line entry point for the DealFlow background worker.

Deployment entry point (runs the transactional outbox and the email outbox, with probes)::

    python -m app.outbox.worker --serve

Single cycle of the transactional outbox, for operators and tests::

    python -m app.outbox.worker --once

Continuous outbox dispatch without email, probes or signal handling (kept for compatibility)::

    python -m app.outbox.worker --poll-interval 5

Only handlers registered in this process can run. ``--once`` and ``--serve`` register the
governance handlers before dispatching. Run one worker per process. Multiple processes are safe
because claims use row locks, leases and fencing tokens.
"""

from __future__ import annotations

import argparse
import threading

from app.db.session import SessionLocal
from app.outbox.runtime import default_worker_id
from app.outbox.service import DispatchResult, dispatch_due_events


def run_once(*, worker_id: str | None = None) -> DispatchResult:
    with SessionLocal() as db:
        return dispatch_due_events(db, worker_id=worker_id or default_worker_id())


def run_forever(
    *,
    poll_interval_seconds: float,
    stop: threading.Event,
    worker_id: str | None = None,
) -> None:
    identity = worker_id or default_worker_id()
    while not stop.is_set():
        result = run_once(worker_id=identity)
        if result.claimed == 0:
            stop.wait(poll_interval_seconds)


def _register_handlers() -> None:
    # Governance handlers (usage alert delivery) must be registered before any dispatch.
    from app.governance.alert_delivery import register_governance_handlers
    from app.providers.verification import register_provider_handlers

    register_governance_handlers()
    register_provider_handlers()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DealFlow background work.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--serve",
        action="store_true",
        help="Run the worker: outbox dispatch and email delivery, with health probes and graceful shutdown.",
    )
    mode.add_argument(
        "--once", action="store_true", help="Run one outbox dispatch cycle and exit."
    )
    mode.add_argument(
        "--poll-interval",
        type=float,
        metavar="SECONDS",
        help="Run outbox dispatch continuously. Does not run email delivery or probes.",
    )
    args = parser.parse_args(argv)

    if args.serve:
        from app.outbox.runtime import serve

        return serve()

    _register_handlers()

    if args.once:
        result = run_once()
        print(
            f"claimed={result.claimed} delivered={result.delivered} "
            f"retried={result.retried} dead_lettered={result.dead_lettered} "
            f"lease_lost={result.lease_lost}"
        )
        return 0

    if args.poll_interval <= 0:
        parser.error("--poll-interval must be positive.")
    try:
        run_forever(poll_interval_seconds=args.poll_interval, stop=threading.Event())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
