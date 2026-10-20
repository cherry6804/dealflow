
"""FastAPI dependency for explicitly configured billing providers."""

from fastapi import Request

from app.billing.providers.base import BillingProvider
from app.billing.providers.errors import ProviderConfigurationError
from app.billing.providers.registry import BillingProviderRegistry


def get_billing_provider_registry(
    request: Request,
) -> BillingProviderRegistry:
    """Return the registry explicitly installed by application setup."""
    registry = getattr(
        request.app.state,
        "billing_provider_registry",
        None,
    )
    if not isinstance(registry, BillingProviderRegistry):
        raise ProviderConfigurationError(
            "Billing providers are not configured."
        )
    return registry


def resolve_billing_provider(
    registry: BillingProviderRegistry,
    provider_name: str,
) -> BillingProvider:
    """Resolve a configured provider without an implicit fallback."""
    return registry.get(provider_name)
