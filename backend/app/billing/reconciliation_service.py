
"""Reconcile verified billing webhook events into audit records."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models.billing_reconciliation_record import (
    BillingReconciliationRecord,
)
from app.db.models.billing_webhook_event import BillingWebhookEvent
from app.db.models.subscription import Subscription


@dataclass(frozen=True)
class ReconciliationResult:
    record: BillingReconciliationRecord
    created: bool


def reconcile_webhook_event(
    db: Session,
    *,
    webhook_event_id: UUID,
) -> ReconciliationResult:
    """Reconcile an event exactly once, even under concurrent requests.

    The caller owns the transaction and must commit or roll it back.
    A subscription reference match does not prove that payment occurred.
    """
    record_model = BillingReconciliationRecord

    existing = db.scalar(
        select(record_model).where(
            record_model.webhook_event_id == webhook_event_id
        )
    )
    if existing is not None:
        return ReconciliationResult(record=existing, created=False)

    event = db.get(BillingWebhookEvent, webhook_event_id)
    if event is None:
        raise ValueError("Billing webhook event was not found.")

    payload = event.payload if isinstance(event.payload, dict) else {}
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}

    subscription_id = data.get("subscription") or payload.get(
        "subscription_id"
    )

    details: dict = {
        "provider": event.provider,
        "provider_event_id": event.provider_event_id,
        "event_type": event.event_type,
        "payment_confirmed": False,
    }
    organization_id = None
    status = record_model.STATUS_FAILED
    summary = "Insufficient subscription evidence to reconcile this event."

    if isinstance(subscription_id, str) and subscription_id.strip():
        subscription_id = subscription_id.strip()

        subscription = db.scalar(
            select(Subscription).where(
                Subscription.provider == event.provider,
                Subscription.provider_subscription_id == subscription_id,
            )
        )

        if subscription is not None:
            status = record_model.STATUS_MATCHED
            organization_id = subscription.organization_id
            summary = (
                "Provider subscription reference matched. "
                "Payment collection has not been verified."
            )
            details["subscription_id"] = str(subscription.id)
            details["provider_subscription_id"] = subscription_id
        else:
            conflicting = db.scalar(
                select(Subscription).where(
                    Subscription.provider_subscription_id == subscription_id
                )
            )
            if conflicting is not None:
                status = record_model.STATUS_MISMATCHED
                organization_id = conflicting.organization_id
                summary = (
                    "Subscription reference exists under a different "
                    "provider; manual review is required."
                )
                details["subscription_id"] = str(conflicting.id)
                details["reason"] = "provider_mismatch"
            else:
                details["reason"] = "subscription_not_found"
                summary = (
                    "Subscription reference did not match a stored "
                    "subscription for this provider."
                )

    values = {
        "webhook_event_id": event.id,
        "organization_id": organization_id,
        "status": status,
        "summary": summary,
        "details": details,
    }

    statement = (
        insert(record_model)
        .values(**values)
        .on_conflict_do_nothing(
            constraint="uq_billing_reconciliation_records_webhook_event"
        )
        .returning(record_model.id)
    )

    created_id = db.execute(statement).scalar_one_or_none()
    db.flush()

    if created_id is not None:
        record = db.get(record_model, created_id)
        if record is None:
            raise RuntimeError("Created reconciliation record could not be loaded.")
        return ReconciliationResult(record=record, created=True)

    # Another transaction created the record first. PostgreSQL's conflict
    # handling waits for that transaction to resolve before this query.
    existing = db.scalar(
        select(record_model).where(
            record_model.webhook_event_id == webhook_event_id
        )
    )
    if existing is None:
        raise RuntimeError(
            "Reconciliation conflict occurred, but the record was not found."
        )

    return ReconciliationResult(record=existing, created=False)


def list_reconciliation_records(
    db: Session,
    *,
    organization_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[BillingReconciliationRecord]:
    """List only reconciliation records belonging to the tenant."""
    statement = (
        select(BillingReconciliationRecord)
        .where(
            BillingReconciliationRecord.organization_id == organization_id
        )
        .order_by(
            BillingReconciliationRecord.created_at.desc(),
            BillingReconciliationRecord.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).all())
