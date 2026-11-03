"""Code-owned registry of external providers (ADR-0032).

The registry is the single source of provider keys for credentials and connections. It lives in
code rather than in a database table, so a provider's adapter, declared operations and status ship
and are reviewed together. Communication-channel providers (E04) register here as well, so there is
one registry for the platform.

A provider appearing here does not make it usable. A provider is usable for an organization only
when a verified connection exists (see ``app.providers.readiness``), and no operation is executable
until its capability gates pass (ADR-0029).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProviderCategory(StrEnum):
    LLM = "llm"
    CHANNEL = "channel"
    SPEECH = "speech"
    EMAIL = "email"


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    display_name: str
    category: ProviderCategory
    # Operations the provider is expected to offer. They are declarations only. Nothing here makes
    # an operation executable, and ``executable`` stays False until the gates for it are enforced.
    declared_operations: tuple[str, ...]
    adapter_implemented: bool
    executable: bool = False


PROVIDERS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        key="openai",
        display_name="OpenAI",
        category=ProviderCategory.LLM,
        declared_operations=("text_generation", "embeddings"),
        adapter_implemented=True,
    ),
)

PROVIDER_BY_KEY: dict[str, ProviderDefinition] = {provider.key: provider for provider in PROVIDERS}
SUPPORTED_PROVIDER_KEYS: frozenset[str] = frozenset(PROVIDER_BY_KEY)

# AI capabilities use the OpenAI adapter until a second LLM provider is registered. Non-AI
# capabilities that need a provider have no registered provider, so they can never be ready.
_AI_CAPABILITY_PREFIX = "ai."


def get_provider(provider_key: str) -> ProviderDefinition | None:
    return PROVIDER_BY_KEY.get(provider_key)


def providers_for_capability(capability_key: str) -> tuple[str, ...]:
    """Provider keys that can satisfy the provider gate of one capability."""
    if capability_key.startswith(_AI_CAPABILITY_PREFIX):
        return tuple(key for key in PROVIDER_BY_KEY if PROVIDER_BY_KEY[key].category is ProviderCategory.LLM)
    return ()
