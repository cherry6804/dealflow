"""Command-line worker that dispatches outbox events.

Run one cycle::

    python -m app.outbox.worker --once

Run continuously::

    python -m app.outbox.worker --poll-interval 5

The worker only dispatches events whose handlers are registered in this
process. Handlers are registered by the modules that own them. Run one worker
per process; multiple processes are safe because claims use row locks and
leases.
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
from uuid import uuid4

from app.db.session import SessionLocal
from app.outbox.service import DispatchResult, dispatch_due_events


def default_worker_id() -> str:
    """Return a worker identity that is unique per process and bounded in length."""
    host = socket.gethostname().replace(" ", "-")[:40]
    return f"{host}:{os.getpid()}:{uuid4().hex[:8]}"[:120]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch Dealsflo outbox events.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--once", action="store_true", help="Run one dispatch cycle and exit."
    )
    mode.add_argument(
        "--poll-interval",
        type=float,
        metavar="SECONDS",
        help="Run continuously, sleeping this long when no events are due.",
    )
    args = parser.parse_args(argv)

    # Governance handlers (usage alert delivery) must be registered before any dispatch.
    from app.governance.alert_delivery import register_governance_handlers

    register_governance_handlers()

    if args.once:
        result = run_once()
        print(
            f"claimed={result.claimed} delivered={result.delivered} "
            f"retried={result.retried} dead_lettered={result.dead_lettered}"
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
