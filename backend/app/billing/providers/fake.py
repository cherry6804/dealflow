
"""Deterministic fake provider for tests and local development."""

import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

from app.billing.providers.base import BillingProvider
from app.billing.providers.errors import ProviderValidationError
from app.billing.providers.schemas import (
    CheckoutRequest,
    CheckoutSession,
    CustomerReference,
    CustomerRequest,
    ProviderCapabilities,
    RefundRequest,
    RefundResult,
    VerifiedWebhookEvent,
)


class FakeBillingProvider(BillingProvider):
    """A fake adapter that never makes external network requests."""

    # Test-only key. Never use this value to authenticate real webhooks.
    _WEBHOOK_SECRET = b"fake-webhook-secret"

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            checkout=True,
            customer_management=True,
            refunds=True,
            recurring_billing=False,
        )

    def create_checkout(
        self, request: CheckoutRequest
    ) -> CheckoutSession:
        return CheckoutSession(
            provider=self.provider_name,
            provider_session_id=f"fake_session_{uuid4().hex}",
            checkout_url=(
                "https://example.invalid/checkout/"
                f"{uuid4().hex}"
            ),
        )

    def create_customer(
        self, request: CustomerRequest
    ) -> CustomerReference:
        return CustomerReference(
            provider=self.provider_name,
            provider_customer_id=f"fake_customer_{uuid4().hex}",
        )

    def create_refund(
        self, request: RefundRequest
    ) -> RefundResult:
        if request.amount_minor is None:
            raise ProviderValidationError(
                "The fake provider requires an explicit refund amount."
            )

        return RefundResult(
            provider=self.provider_name,
            provider_refund_id=f"fake_refund_{uuid4().hex}",
            status="PENDING",
            amount_minor=request.amount_minor,
            currency=request.currency.upper(),
        )

    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> VerifiedWebhookEvent:
        """Verify a test-only HMAC-SHA256 webhook signature."""

        expected_signature = "sha256=" + hmac.new(
            self._WEBHOOK_SECRET,
            payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            raise ProviderValidationError("Invalid webhook signature.")

        try:
            event: Any = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderValidationError(
                "Webhook payload is not valid JSON."
            ) from exc

        if not isinstance(event, dict):
            raise ProviderValidationError(
                "Webhook payload must be a JSON object."
            )

        try:
            return VerifiedWebhookEvent(
                provider=self.provider_name,
                provider_event_id=event["id"],
                event_type=event["type"],
                payload=event,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderValidationError(
                "Webhook payload is missing valid event fields."
            ) from exc
