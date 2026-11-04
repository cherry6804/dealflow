"""Outbox handler that ingests a document after upload (DFR1-016).

Runs in the worker, under the outbox per-event transaction. Ingestion goes through the AI gateway, so the execution gate,
budget and audit apply exactly as for any other AI execution. When AI is disabled, the gate denies, and the outcome is
recorded rather than retried.

A transient provider failure (unavailable or timed out) raises, so the outbox retries the event later. Every other outcome is
final and is returned normally.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext
from app.db.models.outbox_event import OutboxEvent
from app.db.models.user import User
from app.knowledge.events import INGEST_REQUESTED_EVENT
from app.knowledge.service import ingest_document
from app.outbox.service import PermanentHandlerError, register_handler

TRANSIENT_EMBEDDING_REASONS: frozenset[str] = frozenset({"provider_unavailable", "provider_timeout"})


class TransientKnowledgeError(RuntimeError):
    """A provider was briefly unavailable. The outbox retries the event."""


def handle_ingest_requested(db: Session, event: OutboxEvent) -> None:
    try:
        document_id = UUID(str(event.payload["document_id"]))
        user_id = UUID(str(event.payload["user_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentHandlerError("Ingestion payload is invalid.", reason_code="invalid_ingest_payload") from exc

    user = db.get(User, user_id)
    if user is None:
        raise PermanentHandlerError("The uploader no longer exists.", reason_code="uploader_missing")

    result = ingest_document(
        db,
        organization_id=event.organization_id,
        document_id=document_id,
        user_context=CurrentUserContext(user=user),
    )
    if result.outcome == "failed" and result.embedding_reason in TRANSIENT_EMBEDDING_REASONS:
        raise TransientKnowledgeError("The embedding provider is temporarily unavailable.")


def register_knowledge_handlers() -> None:
    """Register the ingestion handler. Safe to call more than once."""
    register_handler(INGEST_REQUESTED_EVENT, handle_ingest_requested)
