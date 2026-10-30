"""Read-only outbox inspection for operators.

Shows event metadata and sanitized errors only. Payloads are never printed.
This is an operator command, not an HTTP endpoint, so it is not exposed to
tenant users.

    python -m app.outbox.reporting --status dead_letter --limit 50
"""

from __future__ import annotations

import argparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal

MAX_LIMIT = 200


def list_events(
    db: Session,
    *,
    status: str | None = None,
    organization_id: UUID | None = None,
    limit: int = 50,
) -> list[OutboxEvent]:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}.")
    if status is not None and status not in OutboxEvent.STATUSES:
        raise ValueError(f"status must be one of {', '.join(OutboxEvent.STATUSES)}.")

    statement = select(OutboxEvent).order_by(OutboxEvent.created_at.desc()).limit(limit)
    if status is not None:
        statement = statement.where(OutboxEvent.status == status)
    if organization_id is not None:
        statement = statement.where(OutboxEvent.organization_id == organization_id)
    return list(db.scalars(statement))


def _format_row(event: OutboxEvent) -> str:
    error = event.last_error or "-"
    return (
        f"{event.id} | {event.organization_id} | {event.event_type} | "
        f"{event.status} | attempts={event.attempts}/{event.max_attempts} | "
        f"available_at={event.available_at.isoformat()} | error={error}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List Dealsflo outbox events.")
    parser.add_argument("--status", choices=OutboxEvent.STATUSES)
    parser.add_argument("--organization-id", type=UUID)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        events = list_events(
            db,
            status=args.status,
            organization_id=args.organization_id,
            limit=args.limit,
        )
    for event in events:
        print(_format_row(event))
    print(f"{len(events)} event(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
