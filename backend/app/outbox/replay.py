"""Operator replay of dead-lettered outbox events (WS3, ADR-0026).

This is an operator command, not an HTTP endpoint. Use it after the cause of a dead letter has
been corrected, for example after an administrator was added to an organization.

    python -m app.outbox.replay --event-id EVENT --organization-id ORG \\
        --operator NAME --reason "Added administrator; re-announce alert" --confirm

Controls:

* **Authorization.** The operator name must appear in ``OUTBOX_OPERATOR_ALLOWLIST``. An empty
  allowlist refuses every replay. The name is asserted by the caller, not authenticated. Access to
  the command therefore depends on who can run it on a host with database credentials. Each
  replay records the name, so the action is attributable to that name.
* **Tenant scope.** The organization identifier must match the event. A mismatch is reported the
  same way as an unknown event, so the command does not reveal other tenants' events.
* **Audit.** Each replay writes an ``outbox_replay_records`` row in the same transaction that
  re-queues the event. It keeps the previous status, attempts, reason and error.
* **Idempotency.** Only dead letters are re-queued. Replaying an event that is already queued
  or delivered changes nothing and reports that.
* **Handler check.** The event type must have a handler in this process, so a replay cannot
  queue work that would dead-letter again for the same reason.
* **Dry run.** Without ``--confirm`` the command prints what it would do and changes nothing.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.outbox_event import OutboxEvent
from app.db.models.outbox_replay_record import OutboxReplayRecord
from app.db.session import SessionLocal
from app.outbox.service import registered_event_types

logger = logging.getLogger("dealflow.worker")

MIN_REASON_LENGTH = 10
MAX_REASON_LENGTH = 500


class ReplayError(Exception):
    """The replay cannot run. The message is safe to show to the operator."""


class ReplayNotAuthorizedError(ReplayError):
    """The operator is not on the replay allowlist."""


@dataclass(frozen=True)
class ReplayOutcome:
    replayed: bool
    status: str
    event_type: str
    dead_letter_reason: str | None
    message: str


def operator_allowlist(allowlist: str) -> frozenset[str]:
    return frozenset(name.strip() for name in allowlist.split(",") if name.strip())


def replay_dead_letter(
    db: Session,
    *,
    event_id: UUID,
    organization_id: UUID,
    operator: str,
    reason: str,
    now: datetime | None = None,
    dry_run: bool = False,
    allowlist: str | None = None,
) -> ReplayOutcome:
    """Re-queue one dead letter in the caller's transaction and commit it. See the module docs."""
    settings = get_settings()
    permitted = operator_allowlist(settings.outbox_operator_allowlist if allowlist is None else allowlist)
    operator = operator.strip()
    if not operator or operator not in permitted:
        raise ReplayNotAuthorizedError("This operator is not authorized to replay outbox events.")

    reason = reason.strip()
    if not MIN_REASON_LENGTH <= len(reason) <= MAX_REASON_LENGTH:
        raise ReplayError(
            f"A reason of {MIN_REASON_LENGTH} to {MAX_REASON_LENGTH} characters is required."
        )

    event = db.scalar(
        select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update()
    )
    if event is None or event.organization_id != organization_id:
        raise ReplayError("No outbox event matches the given identifiers.")

    if event.status != OutboxEvent.STATUS_DEAD_LETTER:
        db.rollback()
        return ReplayOutcome(
            replayed=False,
            status=event.status,
            event_type=event.event_type,
            dead_letter_reason=event.dead_letter_reason,
            message=f"No change: the event is {event.status}, not dead-lettered.",
        )

    if event.event_type not in registered_event_types():
        db.rollback()
        raise ReplayError(
            "No handler for this event type is registered in this process. "
            "Run the replay from a worker build that includes the handler."
        )

    if dry_run:
        db.rollback()
        return ReplayOutcome(
            replayed=False,
            status=event.status,
            event_type=event.event_type,
            dead_letter_reason=event.dead_letter_reason,
            message="Dry run: the event would be re-queued. Add --confirm to re-queue it.",
        )

    current_time = now or datetime.now(UTC)
    db.add(
        OutboxReplayRecord(
            event_id=event.id,
            organization_id=event.organization_id,
            operator=operator,
            reason=reason,
            previous_status=event.status,
            previous_attempts=event.attempts,
            previous_dead_letter_reason=event.dead_letter_reason,
            previous_error=event.last_error,
        )
    )
    event.status = OutboxEvent.STATUS_PENDING
    event.attempts = 0
    event.available_at = current_time
    event.last_error = None
    event.dead_letter_reason = None
    event.locked_by = None
    event.locked_until = None
    event.claim_token = None
    db.commit()

    logger.info(
        "Outbox dead letter replayed",
        extra={
            "outbox_event_id": str(event.id),
            "event_type": event.event_type,
            "organization_id": str(event.organization_id),
            "correlation_id": event.correlation_id or str(event.id),
            "worker_id": operator,
            "outcome": "replayed",
        },
    )
    return ReplayOutcome(
        replayed=True,
        status=OutboxEvent.STATUS_PENDING,
        event_type=event.event_type,
        dead_letter_reason=None,
        message="Re-queued. The next dispatch cycle will run the handler again.",
    )


def main(argv: list[str] | None = None) -> int:
    from app.governance.alert_delivery import register_governance_handlers

    parser = argparse.ArgumentParser(description="Replay a dead-lettered outbox event.")
    parser.add_argument("--event-id", type=UUID, required=True)
    parser.add_argument("--organization-id", type=UUID, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Re-queue the event. Without this flag the command is a dry run.",
    )
    args = parser.parse_args(argv)

    register_governance_handlers()
    try:
        with SessionLocal() as db:
            outcome = replay_dead_letter(
                db,
                event_id=args.event_id,
                organization_id=args.organization_id,
                operator=args.operator,
                reason=args.reason,
                dry_run=not args.confirm,
            )
    except ReplayNotAuthorizedError as exc:
        print(f"refused: {exc}")
        return 3
    except ReplayError as exc:
        print(f"refused: {exc}")
        return 2

    print(f"replayed={str(outcome.replayed).lower()} status={outcome.status} type={outcome.event_type}")
    print(outcome.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
