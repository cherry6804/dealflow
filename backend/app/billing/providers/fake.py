
"""Deterministic fake provider for tests and local development."""

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
)


class FakeBillingProvider(BillingProvider):
    """A fake adapter that never makes external network requests."""

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
