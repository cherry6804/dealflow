"""Audit event service for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.audit_event import (
    AuditDecision,
    AuditEvent,
    AuditEventType,
)
from app.db.session import SessionLocal


def _validate_optional_value(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str | None:
    """Normalize and validate an optional audit value."""
    if value is None:
        return None

    normalized_value = value.strip()

    if not normalized_value:
        raise ValueError(
            f"{field_name} cannot be empty when provided.",
        )

    if len(normalized_value) > max_length:
        raise ValueError(
            f"{field_name} cannot exceed {max_length} characters.",
        )

    return normalized_value


def create_authorization_audit_event(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    action: str,
    decision: AuditDecision,
    permission_key: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """
    Create an authorization audit event in the supplied transaction.

    This low-level function does not commit the transaction. The caller
    owns the transaction boundary.
    """
    normalized_action = action.strip()

    if not normalized_action:
        raise ValueError("Audit action cannot be empty.")

    if len(normalized_action) > 200:
        raise ValueError("Audit action cannot exceed 200 characters.")

    normalized_permission_key = _validate_optional_value(
        permission_key,
        field_name="Permission key",
        max_length=200,
    )

    normalized_resource_type = _validate_optional_value(
        resource_type,
        field_name="Resource type",
        max_length=100,
    )

    normalized_resource_id = _validate_optional_value(
        resource_id,
        field_name="Resource ID",
        max_length=200,
    )

    normalized_correlation_id = _validate_optional_value(
        correlation_id,
        field_name="Correlation ID",
        max_length=200,
    )

    audit_event = AuditEvent(
        user_id=user_id,
        organization_id=organization_id,
        event_type=AuditEventType.AUTHORIZATION.value,
        action=normalized_action,
        decision=decision.value,
        permission_key=normalized_permission_key,
        resource_type=normalized_resource_type,
        resource_id=normalized_resource_id,
        correlation_id=normalized_correlation_id,
    )

    db.add(audit_event)
    db.flush()

    return audit_event


def persist_authorization_audit_event(
    *,
    user_id: UUID,
    organization_id: UUID,
    action: str,
    decision: AuditDecision,
    permission_key: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """
    Persist an authorization audit event in an independent transaction.

    Authorization audit records must survive the request transaction,
    including requests that terminate with an authorization denial.
    """
    with SessionLocal() as db:
        try:
            audit_event = create_authorization_audit_event(
                db,
                user_id=user_id,
                organization_id=organization_id,
                action=action,
                decision=decision,
                permission_key=permission_key,
                resource_type=resource_type,
                resource_id=resource_id,
                correlation_id=correlation_id,
            )

            db.commit()
            db.refresh(audit_event)

            return audit_event
        except Exception:
            db.rollback()
            raise