
"""Tests for the billing webhook event model."""

from uuid import uuid4

from app.db.models.billing_webhook_event import BillingWebhookEvent


def test_webhook_event_defaults_are_configured() -> None:
    columns = BillingWebhookEvent.__table__.c

    assert columns.id.default is not None
    assert columns.status.default is not None
    assert columns.attempt_count.default is not None


def test_webhook_event_fields() -> None:
    event = BillingWebhookEvent(
        provider="fake",
        provider_event_id="evt_test_001",
        event_type="checkout.completed",
        payload={"id": "evt_test_001", "type": "checkout.completed"},
    )

    assert event.id is None
    assert event.provider == "fake"
    assert event.provider_event_id == "evt_test_001"
    assert event.event_type == "checkout.completed"
    assert event.payload["id"] == "evt_test_001"


def test_webhook_event_default_status_is_received() -> None:
    event = BillingWebhookEvent(
        provider="fake",
        provider_event_id="evt_test_002",
        event_type="payment.succeeded",
        payload={"id": "evt_test_002"},
    )

    assert event.status == BillingWebhookEvent.STATUS_RECEIVED


def test_webhook_event_has_provider_event_unique_constraint() -> None:
    constraints = {
        constraint.name
        for constraint in BillingWebhookEvent.__table__.constraints
    }

    assert "uq_billing_webhook_events_provider_event" in constraints


def test_webhook_event_status_values() -> None:
    assert BillingWebhookEvent.STATUS_VALUES == (
        "RECEIVED",
        "PROCESSING",
        "PROCESSED",
        "FAILED",
    )
