
"""Verified billing webhook ingestion and idempotency."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.billing.providers.schemas import VerifiedWebhookEvent
from app.db.models.billing_webhook_event import BillingWebhookEvent


@dataclass(frozen=True)
class WebhookIngestionResult:
    event: BillingWebhookEvent
    created: bool


def ingest_verified_webhook(
    db: Session,
    verified: VerifiedWebhookEvent,
) -> WebhookIngestionResult:
    """Persist a verified event once, even when deliveries race.

    The caller owns the transaction and must commit or roll it back.
    Signature verification must happen before this function is called.
    """
    statement = (
        insert(BillingWebhookEvent)
        .values(
            provider=verified.provider,
            provider_event_id=verified.provider_event_id,
            event_type=verified.event_type,
            payload=verified.payload,
            status=BillingWebhookEvent.STATUS_RECEIVED,
            attempt_count=0,
        )
        .on_conflict_do_nothing(
            constraint="uq_billing_webhook_events_provider_event"
        )
        .returning(BillingWebhookEvent.id)
    )

    inserted_id = db.execute(statement).scalar_one_or_none()

    if inserted_id is not None:
        event = db.execute(
            select(BillingWebhookEvent).where(
                BillingWebhookEvent.id == inserted_id
            )
        ).scalar_one()
        return WebhookIngestionResult(event=event, created=True)

    # A concurrent or earlier delivery already created this event.
    event = db.execute(
        select(BillingWebhookEvent).where(
            BillingWebhookEvent.provider == verified.provider,
            BillingWebhookEvent.provider_event_id
            == verified.provider_event_id,
        )
    ).scalar_one()

    return WebhookIngestionResult(event=event, created=False)
