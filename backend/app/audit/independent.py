"""Independently committed audit records for critical operations (WS6 WP3).

Audit rows written inside a business transaction disappear when that transaction rolls back. That is
the wrong outcome for a denial, or for an attempt to change governance, a budget or a credential. This
module writes such rows in their own database transaction, on a separate connection, and commits them
before the business change is attempted.

Design, recorded in docs/architecture/independent-audit-persistence.md:

- The same ``audit_events`` table and ``AuditEvent`` model are used. No second audit system exists.
- A mutating operation records ``requested`` independently first. If that write fails, the operation
  does not proceed (fail closed). After the change, the caller adds a ``completed`` row in the business
  transaction with ``causation_id`` pointing at the requested row. If the change rolls back, the
  requested row remains and no completed row exists, so no success is claimed.
- A denial is terminal and is recorded once, as ``denied``, independently.
- ``idempotency_key`` is unique per organization. A repeated write with the same key returns the stored
  row instead of creating a second one.
- Metadata is restricted to JSON scalars, lists and objects. Keys that look like secrets are refused,
  so credential material, tokens and passwords cannot be stored by this path.
- Failure raises ``AuditPersistenceError``. Callers must not continue when it is raised.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.attribution import AuditAttribution, AuditAttributionError
from app.db.models.audit_event import AuditEvent
from app.db.models.membership import Membership
from app.db.models.organization import Organization

OUTCOME_REQUESTED = "requested"
OUTCOME_COMPLETED = "completed"
OUTCOME_DENIED = "denied"

IDEMPOTENCY_CONSTRAINT = "uq_audit_events_org_idempotency_key"
MAX_METADATA_BYTES = 4096

# Keys matching this pattern are refused. The list is deliberately broad: a false refusal only means a
# developer renames a field, while a stored secret cannot be taken back.
_SENSITIVE_KEY = re.compile(
    r"secret|token|passw|api[_-]?key|authoriz|cookie|signature|private|cipher|nonce|plaintext",
    re.IGNORECASE,
)


class AuditPersistenceError(RuntimeError):
    """The audit record could not be committed. The governed operation must not proceed."""


class AuditPayloadError(ValueError):
    """The audit metadata is not allowed: a sensitive key, an unsupported value, or too large."""


def _validate_metadata(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditPayloadError(f"Audit metadata keys must be strings at {path}.")
            if _SENSITIVE_KEY.search(key):
                raise AuditPayloadError(f"Audit metadata key {key!r} is not allowed.")
            _validate_metadata(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_metadata(item, f"{path}[{index}]")
        return
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    raise AuditPayloadError(f"Audit metadata value at {path} must be a JSON scalar, list or object.")


def encode_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    """Validate and encode metadata for storage, or return None when there is none."""
    if metadata is None:
        return None
    _validate_metadata(metadata, "metadata")
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise AuditPayloadError("Audit metadata exceeds the size limit.")
    return encoded


def _is_idempotency_violation(exc: IntegrityError) -> bool:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return constraint == IDEMPOTENCY_CONSTRAINT


def _verify_attribution(session: Session, attribution: AuditAttribution) -> None:
    """Confirm the organization and user from the database, on the writer's own connection.

    A caller cannot write under an organization that does not exist or is inactive, or under a user who is
    not an active member of that organization. The check runs before any row is written. The error names no
    identifiers, so it reveals nothing about other tenants.
    """
    organization_active = session.scalar(
        select(Organization.is_active).where(Organization.id == attribution.organization_id)
    )
    if organization_active is not True:
        raise AuditAttributionError("The audit attribution could not be verified.")
    if attribution.actor_user_id is not None:
        membership = session.scalar(
            select(Membership.id).where(
                Membership.organization_id == attribution.organization_id,
                Membership.user_id == attribution.actor_user_id,
                Membership.is_active.is_(True),
            )
        )
        if membership is None:
            raise AuditAttributionError("The audit attribution could not be verified.")


def persist_independent_audit_event(
    source: Session | Engine,
    *,
    attribution: AuditAttribution,
    event_type: str,
    action: str,
    decision: str,
    outcome: str,
    permission_key: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: UUID | None = None,
    idempotency_key: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    """Commit one audit row in its own transaction and return it.

    ``source`` supplies the database only. The caller's transaction is neither used nor committed, so
    the row survives a rollback of that transaction. The attribution is verified against the database
    before the write. Raises ``AuditAttributionError`` when it cannot be verified, ``AuditPayloadError``
    when the metadata is not allowed, and ``AuditPersistenceError`` when the write fails. Nothing is
    written in any of those cases.
    """
    if outcome not in {OUTCOME_REQUESTED, OUTCOME_COMPLETED, OUTCOME_DENIED}:
        raise ValueError(f"Unsupported audit outcome: {outcome!r}.")
    encoded = encode_metadata(metadata)

    organization_id = attribution.organization_id
    actor_user_id = attribution.actor_user_id
    bind = source.get_bind() if isinstance(source, Session) else source
    row = AuditEvent(
        id=uuid4(),
        user_id=actor_user_id,
        organization_id=organization_id,
        event_type=event_type,
        action=action,
        decision=decision,
        outcome=outcome,
        permission_key=permission_key,
        resource_type=resource_type,
        resource_id=resource_id,
        correlation_id=correlation_id or str(uuid4()),
        causation_id=str(causation_id) if causation_id else None,
        idempotency_key=idempotency_key,
        event_metadata=encoded,
    )

    with Session(bind=bind, expire_on_commit=False) as session:
        _verify_attribution(session, attribution)
        try:
            session.add(row)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if idempotency_key is None or not _is_idempotency_violation(exc):
                raise AuditPersistenceError("The audit record could not be written.") from exc
            stored = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.organization_id == organization_id,
                    AuditEvent.idempotency_key == idempotency_key,
                )
            )
            if stored is None:
                raise AuditPersistenceError("The audit record could not be written.") from exc
            return stored
        except SQLAlchemyError as exc:
            session.rollback()
            raise AuditPersistenceError("The audit record could not be written.") from exc
    return row
