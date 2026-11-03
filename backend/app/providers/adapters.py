"""Adapter selection for provider verification (ADR-0032).

Adapters are chosen by provider key from the registry. A provider without an implemented adapter
returns ``None``, and its connections can only end in ``unverified``.
"""

from __future__ import annotations

from app.config import get_settings
from app.providers.base import ProviderAdapter
from app.providers.openai_adapter import OpenAIAdapter


def adapter_for(provider_key: str) -> ProviderAdapter | None:
    settings = get_settings()
    if provider_key == "openai":
        return OpenAIAdapter(
            live_enabled=settings.provider_live_adapters_enabled,
            timeout_seconds=settings.provider_verification_timeout_seconds,
        )
    return None
