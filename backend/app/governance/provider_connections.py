"""Provider connections: registry, secret boundary, verification and the gate check (DFR1-006 / DFR1-011).

Secret boundary: a connection stores only the NAME of an environment variable. The value is read at
verification and at gate time, is passed to the probe, and is never stored, logged, audited or returned.

Verification: a provider is ``verified`` only after its probe succeeded. The probe registry ``PROBES`` is
empty, so no provider is verified until a real probe is registered. Until then every connection stays
``not_verified`` and the gate denies. Nothing here claims a provider is connected.

Health age: a verified connection must have been verified within ``provider_health_max_age_seconds``, and its
secret must still be present, or the gate denies (fail closed).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.provider_connection import PROVIDER_KINDS, ProviderConnection

PROVIDER_EVENT_TYPE = "governance"
PROVIDER_AUDIT_ACTION = "provider.connection"
SECRET_REF_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,119}$")

REASON_PROVIDER_NOT_CONNECTED = "provider_not_connected"
REASON_PROVIDER_UNHEALTHY = "provider_unhealthy"
REASON_PROVIDER_HEALTH_STALE = "provider_health_stale"

ERROR_SECRET_MISSING = "secret_missing"
ERROR_NO_PROBE = "no_probe_available"
ERROR_PROBE_FAILED = "probe_failed"


class ProviderConnectionError(Exception):
    """A provider connection request breaks a rule."""


class ProviderConnectionNotFoundError(ProviderConnectionError):
    """No connection with this ID exists in the organization."""


class ProviderConnectionExistsError(ProviderConnectionError):
    """The organization already has a connection of this kind."""


class ProbeFailedError(Exception):
    """A provider probe reported a failure. Only its short code is kept."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# Registered probes, one per provider kind. Empty until a real provider adapter exists.
PROBES: dict[str, Callable[[str], None]] = {}


def secret_value(secret_ref: str) -> str | None:
    """Read the secret by environment variable name. The only place a secret value is read."""
    value = os.environ.get(secret_ref)
    return value if value else None


def secret_present(secret_ref: str) -> bool:
    return secret_value(secret_ref) is not None


def _audit(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    connection: ProviderConnection,
    metadata: dict[str, object],
) -> None:
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=PROVIDER_EVENT_TYPE,
            action=action,
            decision="allowed",
            permission_key="governance.providers.manage",
            resource_type="provider_connection",
            resource_id=str(connection.id),
            event_metadata=json.dumps(
                {"provider_kind": connection.provider_kind, **metadata}, sort_keys=True
            ),
        )
    )
    db.flush()


def _get(db: Session, *, organization_id: UUID, connection_id: UUID) -> ProviderConnection:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == connection_id,
            ProviderConnection.organization_id == organization_id,
        )
    )
    if connection is None:
        raise ProviderConnectionNotFoundError("Provider connection not found.")
    return connection


def create_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    provider_kind: str,
    display_name: str,
    secret_ref: str,
) -> ProviderConnection:
    """Register a provider connection. It starts ``not_verified`` and is audited."""
    if provider_kind not in PROVIDER_KINDS:
        raise ProviderConnectionError("Unknown provider kind.")
    cleaned_name = display_name.strip()
    if not cleaned_name or len(cleaned_name) > 120:
        raise ProviderConnectionError("Display name must be 1 to 120 characters.")
    if not SECRET_REF_PATTERN.fullmatch(secret_ref):
        raise ProviderConnectionError(
            "The secret reference must be an environment variable name in capitals, digits and underscores."
        )
    existing = db.scalar(
        select(ProviderConnection.id).where(
            ProviderConnection.organization_id == organization_id,
            ProviderConnection.provider_kind == provider_kind,
        )
    )
    if existing is not None:
        raise ProviderConnectionExistsError("This organization already has a connection of this kind.")
    connection = ProviderConnection(
        organization_id=organization_id,
        provider_kind=provider_kind,
        display_name=cleaned_name,
        secret_ref=secret_ref,
        status="not_verified",
        created_by_user_id=actor_user_id,
    )
    db.add(connection)
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=PROVIDER_AUDIT_ACTION + ".created",
        connection=connection,
        metadata={"status": "not_verified"},
    )
    return connection


def verify_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    connection_id: UUID,
    now: datetime | None = None,
) -> ProviderConnection:
    """Run the provider probe and set the status from the real result. Never sets ``verified`` on assumption."""
    current_time = now if now is not None else datetime.now(UTC)
    connection = _get(db, organization_id=organization_id, connection_id=connection_id)
    if connection.status == "disabled":
        raise ProviderConnectionError("A disabled connection cannot be verified. Create a new connection.")

    value = secret_value(connection.secret_ref)
    probe = PROBES.get(connection.provider_kind)
    if value is None:
        connection.status = "unhealthy"
        connection.last_error_code = ERROR_SECRET_MISSING
    elif probe is None:
        connection.status = "not_verified"
        connection.last_error_code = ERROR_NO_PROBE
    else:
        try:
            probe(value)
        except ProbeFailedError as error:
            connection.status = "unhealthy"
            connection.last_error_code = error.code
        except Exception:  # noqa: BLE001 - a probe may raise any error; only a fixed code is recorded.
            connection.status = "unhealthy"
            connection.last_error_code = ERROR_PROBE_FAILED
        else:
            connection.status = "verified"
            connection.last_verified_at = current_time
            connection.last_error_code = None
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=PROVIDER_AUDIT_ACTION + ".verified",
        connection=connection,
        metadata={"status": connection.status, "error_code": connection.last_error_code},
    )
    return connection


def disable_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    connection_id: UUID,
) -> ProviderConnection:
    connection = _get(db, organization_id=organization_id, connection_id=connection_id)
    connection.status = "disabled"
    connection.last_error_code = None
    db.flush()
    _audit(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=PROVIDER_AUDIT_ACTION + ".disabled",
        connection=connection,
        metadata={"status": "disabled"},
    )
    return connection


def list_connections(db: Session, *, organization_id: UUID) -> list[ProviderConnection]:
    return list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.organization_id == organization_id)
            .order_by(ProviderConnection.provider_kind)
        ).all()
    )


def provider_gate(
    db: Session,
    *,
    organization_id: UUID,
    provider_kind: str | None,
    now: datetime | None = None,
) -> str | None:
    """Return the denial reason for a required provider, or None when a fresh verified connection exists."""
    if provider_kind is None:
        # A capability that declares no provider kind can never be satisfied. It fails closed.
        return REASON_PROVIDER_NOT_CONNECTED
    current_time = now if now is not None else datetime.now(UTC)
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.organization_id == organization_id,
            ProviderConnection.provider_kind == provider_kind,
        )
    )
    if connection is None or connection.status in ("not_verified", "disabled"):
        return REASON_PROVIDER_NOT_CONNECTED
    if connection.status == "unhealthy":
        return REASON_PROVIDER_UNHEALTHY
    # status == "verified": the secret must still be present, and the check must be recent.
    if not secret_present(connection.secret_ref):
        return REASON_PROVIDER_UNHEALTHY
    max_age = timedelta(seconds=get_settings().provider_health_max_age_seconds)
    if connection.last_verified_at is None or current_time - connection.last_verified_at > max_age:
        return REASON_PROVIDER_HEALTH_STALE
    return None
