"""Declared event triggers for workflows, delivered through the transactional outbox (DFR1-024).

A domain change publishes an event in the same transaction as the change. The outbox delivers it to the handler, which starts one run
for each published workflow of the same organization that declares that event. Delivery is at least once, so the handler is
idempotent: each run has a key made of the event type, the event key and the workflow, and a second delivery finds the run and starts
nothing. An event caused by a workflow run never starts another run, which stops event-trigger loops.

Only the events listed in ``TRIGGER_EVENTS`` (from the schema) can be published, and only ``lead.created`` is emitted by a CRM service
in this release. The others are declared so workflows can name them, and they fire once their emitting code exists.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.workflow import WorkflowDefinition, WorkflowVersion
from app.outbox.service import (
    InvalidOutboxEventError,
    PermanentHandlerError,
    enqueue_event,
    register_handler,
)
from app.workflows.runtime import start_for_event
from app.workflows.schema import TRIGGER_EVENT, TRIGGER_EVENTS

WORKFLOW_EVENT_OUTBOX_TYPE = "workflow.event_published"
MAX_EVENT_KEY = 120


def publish_event(db: Session, *, organization_id: UUID, event_type: str, event_key: str,
                  data: dict[str, Any] | None = None, source_execution_id: UUID | None = None) -> None:
    """Record a declared event in the caller's transaction. The caller commits, and a rollback discards the event with the change."""
    if event_type not in TRIGGER_EVENTS:
        raise InvalidOutboxEventError(f"{event_type!r} is not a supported workflow event.")
    key = event_key.strip()
    if not key or len(key) > MAX_EVENT_KEY:
        raise InvalidOutboxEventError("The event key must be 1 to 120 characters.")
    enqueue_event(
        db,
        organization_id=organization_id,
        event_type=WORKFLOW_EVENT_OUTBOX_TYPE,
        aggregate_type="workflow_event",
        aggregate_id=f"{event_type}:{key}",
        idempotency_key=f"workflow-event:{organization_id}:{event_type}:{key}",
        payload={
            "event_type": event_type,
            "event_key": key,
            "source_execution_id": str(source_execution_id) if source_execution_id else None,
            "data": dict(data or {}),
        },
    )


def _eligible(db: Session, organization_id: UUID, event_type: str) -> list[tuple[WorkflowDefinition, WorkflowVersion]]:
    rows: list[tuple[WorkflowDefinition, WorkflowVersion]] = []
    for workflow in db.scalars(select(WorkflowDefinition).where(
        WorkflowDefinition.organization_id == organization_id,
        WorkflowDefinition.status == WorkflowDefinition.STATUS_PUBLISHED,
        WorkflowDefinition.current_version_id.is_not(None),
    ).order_by(WorkflowDefinition.id)).all():
        version = db.get(WorkflowVersion, workflow.current_version_id)
        if version is None or version.organization_id != organization_id:
            continue
        trigger = version.configuration.get("trigger") or {}
        if trigger.get("type") == TRIGGER_EVENT and trigger.get("event") == event_type:
            rows.append((workflow, version))
    return rows


def handle_workflow_event(db: Session, event: Any) -> None:
    """Outbox handler: start one run for each eligible workflow. Duplicate deliveries start nothing new."""
    payload = event.payload or {}
    event_type = payload.get("event_type")
    event_key = payload.get("event_key")
    if not isinstance(event_type, str) or not isinstance(event_key, str) or event_type not in TRIGGER_EVENTS:
        raise PermanentHandlerError("The workflow event is invalid.", reason_code="invalid_workflow_event")
    if payload.get("source_execution_id"):
        return  # An event caused by a workflow run never starts another run.
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for workflow, version in _eligible(db, event.organization_id, event_type):
        start_for_event(db, organization_id=event.organization_id, workflow=workflow, version=version,
                        event_type=event_type, event_key=event_key, data=data)


def register_workflow_handlers() -> None:
    """Register the event handler and the execution handler with the outbox. Safe to call more than once."""
    from app.workflows.handlers import register_execution_handler

    register_handler(WORKFLOW_EVENT_OUTBOX_TYPE, handle_workflow_event)
    register_execution_handler()
