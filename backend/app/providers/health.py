"""Stale-connection detection for provider health (ADR-0032).

Readiness is derived at read time, so a connection whose last successful verification is older than the freshness
window is already not ready (``app.providers.readiness``). This module makes that transition observable: the worker
records one audit row per staleness episode, so operators can see when a provider stopped being usable and why.

A staleness episode is identified by the connection and its last successful verification time. The audit idempotency
key contains both, so repeated sweeps and concurrent workers record each episode once. A new successful verification
starts a new episode with a different key.

Detection never changes the connection row and never contacts a provider. A failure to write one audit row is logged
without any secret or provider message, and does not stop the sweep for other connections.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.audit.attribution import register_system_actor, system_attribution
from app.audit.independent import (
    OUTCOME_COMPLETED,
    AuditPersistenceError,
    persist_independent_audit_event,
)
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.provider_connection import ProviderConnection
from app.providers.service import PROVIDER_CONNECTION_AUDIT_EVENT

logger = logging.getLogger("dealflow.worker")

PROVIDER_HEALTH_SYSTEM_ACTOR = register_system_actor("provider_health")
STALE_ACTION = "provider_connection.stale"
STALE_DECISION = "allowed"


def _stale_cutoff(now: datetime) -> datetime:
    return now - timedelta(hours=get_settings().provider_connection_freshness_hours)


_PAGE_SIZE = 100


def detect_stale_connections(db: Session, *, now: datetime, limit: int = 100) -> int:
    """Record up to ``limit`` new staleness episodes and return how many were recorded in this sweep.

    The sweep pages through every stale connection in (last verified time, id) order. Episodes that are already
    recorded are skipped and do not count toward ``limit``. So a backlog larger than ``limit`` is worked through over
    successive sweeps, and no connection is starved behind episodes that were already recorded.

    Each row is committed in its own transaction, so a rollback of the caller's transaction does not remove the
    observation.
    """
    cutoff = _stale_cutoff(now)
    recorded = 0
    cursor: tuple[datetime, UUID] | None = None
    while recorded < limit:
        statement = select(ProviderConnection).where(
            ProviderConnection.status == ProviderConnection.STATUS_CONNECTED,
            ProviderConnection.last_verified_at.is_not(None),
            ProviderConnection.last_verified_at < cutoff,
        )
        if cursor is not None:
            statement = statement.where(tuple_(ProviderConnection.last_verified_at, ProviderConnection.id) > cursor)
        batch = db.scalars(
            statement.order_by(ProviderConnection.last_verified_at, ProviderConnection.id).limit(_PAGE_SIZE)
        ).all()
        if not batch:
            break
        for connection in batch:
            if _record_stale(db, connection):
                recorded += 1
                if recorded >= limit:
                    break
        last = batch[-1]
        if last.last_verified_at is None:  # Excluded by the query; kept to narrow the type.
            break
        cursor = (last.last_verified_at, last.id)
    return recorded


def _episode_key(connection: ProviderConnection, verified_at: datetime) -> str:
    return f"provider-stale:{connection.id}:{verified_at.isoformat()}"


def _already_recorded(db: Session, connection: ProviderConnection, verified_at: datetime) -> bool:
    return (
        db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.organization_id == connection.organization_id,
                AuditEvent.idempotency_key == _episode_key(connection, verified_at),
            )
        )
        is not None
    )


def _record_stale(db: Session, connection: ProviderConnection) -> bool:
    """Write the staleness row for this episode. Returns True when a write was attempted, False when already recorded."""
    verified_at = connection.last_verified_at
    if verified_at is None:  # Excluded by the query; kept to narrow the type.
        return False
    if _already_recorded(db, connection, verified_at):
        return False
    try:
        persist_independent_audit_event(
            db,
            attribution=system_attribution(
                organization_id=connection.organization_id,
                capability=PROVIDER_HEALTH_SYSTEM_ACTOR,
            ),
            event_type=PROVIDER_CONNECTION_AUDIT_EVENT,
            action=STALE_ACTION,
            decision=STALE_DECISION,
            outcome=OUTCOME_COMPLETED,
            permission_key=None,
            resource_type="provider_connection",
            resource_id=str(connection.id),
            idempotency_key=_episode_key(connection, verified_at),
            metadata={
                "provider_key": connection.provider_key,
                "last_verified_at": verified_at.isoformat(),
                "credential_version": connection.verified_credential_version,
            },
        )
    except AuditPersistenceError:
        # Not recorded, so the episode stays eligible for the next sweep.
        logger.error(
            "Provider staleness audit could not be recorded",
            extra={"connection_id": str(connection.id), "organization_id": str(connection.organization_id)},
        )
        return False
    return True


