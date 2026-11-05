"""Outbox handler that runs queued workflow executions and resumes them after an approval or a delay (DFR1-024)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.outbox.service import PermanentHandlerError, register_handler
from app.workflows.runtime import EXECUTION_REQUESTED_EVENT
from app.workflows.runtime import handle_execution_requested as run_requested


def handle_execution_requested(db: Session, event: object) -> None:
    payload = getattr(event, "payload", None) or {}
    try:
        execution_id = UUID(str(payload["execution_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentHandlerError("The execution event is invalid.", reason_code="invalid_execution_payload") from exc
    organization_id = event.organization_id
    run_requested(db, execution_id, organization_id)


def register_execution_handler() -> None:
    register_handler(EXECUTION_REQUESTED_EVENT, handle_execution_requested)
