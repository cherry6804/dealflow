
"""Provider-independent billing integration contracts."""

from app.billing.providers.base import BillingProvider
from app.billing.providers.errors import (
    BillingProviderError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConflictError,
    ProviderOperationUnsupportedError,
    ProviderUnavailableError,
    ProviderValidationError,
)
from app.billing.providers.fake import FakeBillingProvider
from app.billing.providers.registry import BillingProviderRegistry
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

__all__ = [
    "BillingProvider",
    "BillingProviderError",
    "BillingProviderRegistry",
    "CheckoutRequest",
    "CheckoutSession",
    "CustomerReference",
    "CustomerRequest",
    "FakeBillingProvider",
    "ProviderAuthenticationError",
    "ProviderCapabilities",
    "ProviderConfigurationError",
    "ProviderConflictError",
    "ProviderOperationUnsupportedError",
    "ProviderUnavailableError",
    "ProviderValidationError",
    "RefundRequest",
    "RefundResult",
    "VerifiedWebhookEvent",
]
