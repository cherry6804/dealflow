"""Scheduled privacy maintenance (DFR1-050): export expiry and retention enforcement.

Run from an external scheduler, the same way as the other jobs:

    python -m app.governance.privacy_maintenance

Each export and each organization is processed in its own transaction. A failure is rolled back,
counted and logged with the exception type only, never a message or a payload, and the run carries
on with the next item. Re-running is safe: expiry and retention are both idempotent.

Nothing in this repository schedules this command. Until a scheduler runs it, expired exports are
still refused on access, but their stored objects are removed only when someone downloads them.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.privacy_records import PrivacyDataRequest, RetentionPolicy
from app.db.session import SessionLocal
from app.governance.privacy import STATUS_READY, STATUS_READY_PARTIAL
from app.governance.privacy_execution import enforce_retention, expire_request_export
from app.storage import ObjectStorage, get_object_storage

logger = logging.getLogger(__name__)


def _log_failure(stage: str, organization_id: UUID, error: Exception) -> None:
    logger.error(
        "privacy_maintenance_failed",
        extra={
            "stage": stage,
            "organization_id": str(organization_id),
            "error_type": type(error).__name__,
        },
    )


def run_export_expiry(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    now: datetime,
    storage: ObjectStorage,
) -> Counter:
    """Expire every ready export whose window has passed, and remove its stored object."""
    report: Counter = Counter()
    with session_factory() as db:
        due = db.execute(
            select(PrivacyDataRequest.id, PrivacyDataRequest.organization_id).where(
                PrivacyDataRequest.request_type == PrivacyDataRequest.TYPE_EXPORT,
                PrivacyDataRequest.status.in_([STATUS_READY, STATUS_READY_PARTIAL]),
                PrivacyDataRequest.expires_at.is_not(None),
                PrivacyDataRequest.expires_at <= now,
            )
        ).all()
    report["due"] = len(due)

    for request_id, organization_id in due:
        try:
            with session_factory() as db:
                request = db.scalar(
                    select(PrivacyDataRequest).where(
                        PrivacyDataRequest.id == request_id,
                        PrivacyDataRequest.organization_id == organization_id,
                    )
                )
                if request is None:
                    report["missing"] += 1
                    continue
                expired = expire_request_export(db, request, storage=storage, now=now)
                db.commit()
            report["expired" if expired else "unchanged"] += 1
        except Exception as error:  # noqa: BLE001 - one export must not stop the run.
            report["failed"] += 1
            _log_failure("export_expiry", organization_id, error)
    return report


def run_retention(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    now: datetime,
    storage: ObjectStorage,
) -> Counter:
    """Apply each organization's retention periods. One transaction per organization."""
    report: Counter = Counter()
    with session_factory() as db:
        organization_ids = db.scalars(
            select(RetentionPolicy.organization_id).distinct()
        ).all()
    report["organizations"] = len(organization_ids)

    for organization_id in organization_ids:
        try:
            with session_factory() as db:
                outcome = enforce_retention(
                    db, organization_id=organization_id, storage=storage, now=now
                )
                db.commit()
            for item in outcome.values():
                report[f"retention_{item['outcome']}"] += 1
        except Exception as error:  # noqa: BLE001 - one organization must not stop the run.
            report["failed"] += 1
            _log_failure("retention", organization_id, error)
    return report


def run(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    now: datetime | None = None,
    storage: ObjectStorage | None = None,
) -> Counter:
    current = now if now is not None else datetime.now(UTC)
    store = storage if storage is not None else get_object_storage()
    report: Counter = Counter()
    report.update(run_export_expiry(session_factory, now=current, storage=store))
    report.update(run_retention(session_factory, now=current, storage=store))
    return report


def main() -> int:
    report = run()
    summary = (
        " ".join(f"{key}={value}" for key, value in sorted(report.items()))
        or "nothing_due"
    )
    print(f"privacy_maintenance {summary}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
