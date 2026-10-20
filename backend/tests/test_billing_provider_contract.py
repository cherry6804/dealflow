
"""Tests for the provider-independent billing contract."""

from uuid import uuid4

import pytest

from app.billing.providers import (
    BillingProviderRegistry,
    CheckoutRequest,
    ProviderConfigurationError,
    ProviderValidationError,
    RefundRequest,
)
from app.billing.providers.fake import FakeBillingProvider


def test_fake_provider_creates_normalized_checkout() -> None:
    provider = FakeBillingProvider()
    request = CheckoutRequest(
        organization_id=uuid4(),
        subscription_id=uuid4(),
        amount_minor=49900,
        description="Solo monthly subscription",
        success_url="https://dealflow.example/success",
        cancel_url="https://dealflow.example/cancel",
        idempotency_key="checkout-test-001",
    )

    result = provider.create_checkout(request)

    assert result.provider == "fake"
    assert result.provider_session_id.startswith("fake_session_")
    assert result.checkout_url.startswith(
        "https://example.invalid/checkout/"
    )


def test_fake_provider_creates_customer_reference() -> None:
    provider = FakeBillingProvider()

    result = provider.create_customer(
        __import__(
            "app.billing.providers.schemas",
            fromlist=["CustomerRequest"],
        ).CustomerRequest(
            organization_id=uuid4(),
            email="test@example.com",
            name="Test Organization",
            idempotency_key="customer-test-001",
        )
    )

    assert result.provider == "fake"
    assert result.provider_customer_id.startswith("fake_customer_")


def test_fake_provider_requires_refund_amount() -> None:
    provider = FakeBillingProvider()
    request = RefundRequest(
        organization_id=uuid4(),
        provider_payment_id="fake_payment_001",
        idempotency_key="refund-test-001",
    )

    with pytest.raises(ProviderValidationError):
        provider.create_refund(request)


def test_registry_resolves_registered_provider() -> None:
    registry = BillingProviderRegistry()
    registry.register("fake", FakeBillingProvider)

    assert registry.get("FAKE").provider_name == "fake"


def test_registry_rejects_unconfigured_provider() -> None:
    registry = BillingProviderRegistry()

    with pytest.raises(ProviderConfigurationError):
        registry.get("razorpay")


def test_registry_rejects_mismatched_provider_factory() -> None:
    registry = BillingProviderRegistry()
    registry.register("razorpay", FakeBillingProvider)

    with pytest.raises(ProviderConfigurationError):
        registry.get("razorpay")
