"""Adapter contract for provider verification (ADR-0032).

An adapter answers one question: does this credential authenticate with the provider right now? It
never returns the credential, and its result carries only a stable reason code, never a provider
response body, so a failed check cannot leak a secret into logs or history.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class VerificationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    TIMED_OUT = "timed_out"
    # The adapter did not contact the provider, because live access is disabled. This is never
    # reported as a success.
    NOT_VERIFIED = "not_verified"


@dataclass(frozen=True)
class VerificationResult:
    outcome: VerificationOutcome
    reason_code: str | None
    latency_ms: int
    adapter_version: str


class ProviderAdapter(Protocol):
    provider_key: str
    adapter_version: str

    def verify(self, api_key: str) -> VerificationResult:
        """Check the credential. Must not raise for provider failures and must not log the key."""
        ...
