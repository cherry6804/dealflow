
"""Tests for billing webhook verification contracts."""

import hashlib
import hmac
import json

import pytest

from app.billing.providers.errors import ProviderValidationError
from app.billing.providers.fake import FakeBillingProvider
from app.billing.providers.schemas import VerifiedWebhookEvent


TEST_SECRET = b"fake-webhook-secret"


def sign_payload(payload: bytes) -> str:
    """Create the fake provider's test signature."""
    digest = hmac.new(
        TEST_SECRET,
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def test_valid_webhook_signature_returns_normalized_event() -> None:
    provider = FakeBillingProvider()
    payload = json.dumps(
        {
            "id": "evt_test_001",
            "type": "checkout.completed",
            "data": {"subscription_id": "sub_test_001"},
        },
        separators=(",", ":"),
    ).encode()

    event = provider.verify_webhook(payload, sign_payload(payload))

    assert isinstance(event, VerifiedWebhookEvent)
    assert event.provider == "fake"
    assert event.provider_event_id == "evt_test_001"
    assert event.event_type == "checkout.completed"
    assert event.payload["data"]["subscription_id"] == "sub_test_001"


def test_invalid_webhook_signature_is_rejected() -> None:
    provider = FakeBillingProvider()
    payload = b'{"id":"evt_test_001","type":"checkout.completed"}'

    with pytest.raises(ProviderValidationError, match="Invalid webhook signature"):
        provider.verify_webhook(payload, "sha256=invalid")


def test_modified_payload_fails_signature_verification() -> None:
    provider = FakeBillingProvider()
    original = b'{"id":"evt_test_001","type":"checkout.completed"}'
    modified = b'{"id":"evt_test_002","type":"checkout.completed"}'

    with pytest.raises(ProviderValidationError, match="Invalid webhook signature"):
        provider.verify_webhook(modified, sign_payload(original))


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"[]",
        b'"string"',
        b"null",
    ],
)
def test_invalid_json_or_non_object_payload_is_rejected(
    payload: bytes,
) -> None:
    provider = FakeBillingProvider()

    with pytest.raises(ProviderValidationError):
        provider.verify_webhook(payload, sign_payload(payload))


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"id": "evt_test_001"},
        {"type": "checkout.completed"},
        {"id": "", "type": "checkout.completed"},
        {"id": "evt_test_001", "type": ""},
    ],
)
def test_missing_or_invalid_event_fields_are_rejected(
    event: dict[str, object],
) -> None:
    provider = FakeBillingProvider()
    payload = json.dumps(event).encode()

    with pytest.raises(ProviderValidationError):
        provider.verify_webhook(payload, sign_payload(payload))
