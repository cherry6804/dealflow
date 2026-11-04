"""Outbox handler that runs queued agent executions (DFR1-019).

The worker runs this inside the outbox's per-event transaction. A duplicate or late event finds the execution already running,
waiting or finished, and does nothing. A resumed event after an approval finds the execution queued and runs it on from the
approved step. The handler does not retry provider failures itself: each model step already has bounded retries, and a step
that still fails ends the execution with a recorded reason.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.runtime import EXECUTION_REQUESTED_EVENT, lock_execution, run_execution
from app.auth.dependencies import CurrentUserContext
from app.db.models.agent import AgentExecution
from app.db.models.outbox_event import OutboxEvent
from app.db.models.user import User
from app.outbox.service import PermanentHandlerError, register_handler


def handle_execution_requested(db: Session, event: OutboxEvent) -> None:
    try:
        execution_id = UUID(str(event.payload["execution_id"]))
        user_id = UUID(str(event.payload["user_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentHandlerError("The execution event is invalid.", reason_code="invalid_execution_payload") from exc

    execution = lock_execution(db, organization_id=event.organization_id, execution_id=execution_id)
    if execution is None:
        return
    if execution.status not in (AgentExecution.STATUS_QUEUED, AgentExecution.STATUS_RUNNING):
        return  # A duplicate, a late event, or an execution waiting for a decision.

    user = db.get(User, user_id)
    if user is None or user.id != execution.initiated_by_user_id:
        execution.status = AgentExecution.STATUS_FAILED
        execution.failure_reason = "initiator_missing"
        db.flush()
        return

    run_execution(db, execution, CurrentUserContext(user=user))


def register_agent_handlers() -> None:
    """Register the execution handler. Safe to call more than once."""
    register_handler(EXECUTION_REQUESTED_EVENT, handle_execution_requested)
