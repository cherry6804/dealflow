"""Scheduled usage maintenance (DFR1-017): release expired AI usage reservations.

Run from an external scheduler, like the other jobs:

    python -m app.governance.usage_maintenance

Each batch is committed on its own. A failure is rolled back, counted and logged with the exception type
only, and the run stops, so a later run continues from the same place. Re-running is safe: an entry is
released only while it is still reserved.

Nothing in this repository schedules this command. Until a scheduler runs it, an unsettled reservation keeps
its budget until the next run. Its quantity is never counted as consumed.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.governance.usage_ledger import release_expired

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
MAX_BATCHES_PER_RUN = 1000


def run(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    now: datetime | None = None,
    batch_size: int = BATCH_SIZE,
) -> Counter:
    """Release every expired reservation, one committed batch at a time."""
    current = now if now is not None else datetime.now(UTC)
    report: Counter = Counter()
    for _ in range(MAX_BATCHES_PER_RUN):
        try:
            with session_factory() as db:
                released = release_expired(db, now=current, limit=batch_size)
                db.commit()
        except Exception as error:  # noqa: BLE001 - reported, then the run stops for a later retry.
            report["failed"] += 1
            logger.error(
                "usage_maintenance_failed",
                extra={"stage": "reservation_expiry", "error_type": type(error).__name__},
            )
            break
        report["released"] += released
        if released < batch_size:
            break
    return report


def main() -> int:
    report = run()
    summary = " ".join(f"{key}={value}" for key, value in sorted(report.items())) or "nothing_expired"
    print(f"usage_maintenance {summary}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
