
"""Explicit registry for billing provider implementations."""

from collections.abc import Callable

from app.billing.providers.base import BillingProvider
from app.billing.providers.errors import (
    ProviderConfigurationError,
)


ProviderFactory = Callable[[], BillingProvider]


class BillingProviderRegistry:
    """Resolve provider implementations by their stable identifier."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(
        self,
        name: str,
        factory: ProviderFactory,
    ) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("Provider name must not be empty.")
        if normalized_name in self._factories:
            raise ValueError(
                f"Provider '{normalized_name}' is already registered."
            )
        self._factories[normalized_name] = factory

    def get(self, name: str) -> BillingProvider:
        normalized_name = name.strip().lower()
        factory = self._factories.get(normalized_name)
        if factory is None:
            raise ProviderConfigurationError(
                f"Billing provider '{normalized_name}' is not configured."
            )

        provider = factory()
        if provider.provider_name.strip().lower() != normalized_name:
            raise ProviderConfigurationError(
                "Provider factory returned an unexpected provider."
            )
        return provider
