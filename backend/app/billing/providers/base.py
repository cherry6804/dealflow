
"""Abstract contract implemented by payment provider adapters."""

from abc import ABC, abstractmethod

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


class BillingProvider(ABC):
    """Provider-neutral interface for payment operations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable, non-secret provider identifier."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare supported provider operations."""

    @abstractmethod
    def create_checkout(
        self, request: CheckoutRequest
    ) -> CheckoutSession:
        """Create a hosted checkout session."""

    @abstractmethod
    def create_customer(
        self, request: CustomerRequest
    ) -> CustomerReference:
        """Create or resolve a provider-side customer."""

    @abstractmethod
    def create_refund(
        self, request: RefundRequest
    ) -> RefundResult:
        """Request a refund against an existing provider payment."""

    @abstractmethod
    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> VerifiedWebhookEvent:
        """Verify raw webhook bytes and return a normalized event."""
