"""OpenAI verification adapter (ADR-0032, decision D1).

Verification calls the models listing endpoint with the stored key. Live access is controlled by
``PROVIDER_LIVE_ADAPTERS_ENABLED``, which is off by default and is never enabled in CI. When it is
off, this adapter does not contact the network and reports ``not_verified``.

Response bodies are never read into results, logged or stored, so a provider error cannot carry a
credential out of the system.
"""

from __future__ import annotations

import time

import httpx

from app.providers.base import VerificationOutcome, VerificationResult

ADAPTER_VERSION = "openai-models-v1"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
_REJECTED_STATUSES = frozenset({401, 403})


class OpenAIAdapter:
    provider_key = "openai"
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        *,
        live_enabled: bool,
        timeout_seconds: float,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._live_enabled = live_enabled
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def verify(self, api_key: str) -> VerificationResult:
        if not self._live_enabled:
            return VerificationResult(
                outcome=VerificationOutcome.NOT_VERIFIED,
                reason_code="live_adapter_disabled",
                latency_ms=0,
                adapter_version=self.adapter_version,
            )

        started = time.monotonic()
        try:
            with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.TimeoutException:
            return self._result(VerificationOutcome.TIMED_OUT, "verification_timed_out", started)
        except httpx.HTTPError:
            return self._result(VerificationOutcome.TRANSIENT_FAILURE, "provider_unreachable", started)

        status_code = response.status_code
        if 200 <= status_code < 300:
            return self._result(VerificationOutcome.SUCCEEDED, None, started)
        if status_code in _REJECTED_STATUSES:
            return self._result(VerificationOutcome.PERMANENT_FAILURE, "provider_rejected_credential", started)
        if status_code == 429 or status_code >= 500:
            return self._result(VerificationOutcome.TRANSIENT_FAILURE, "provider_unavailable", started)
        return self._result(VerificationOutcome.PERMANENT_FAILURE, "unexpected_provider_response", started)

    def _result(self, outcome: VerificationOutcome, reason_code: str | None, started: float) -> VerificationResult:
        return VerificationResult(
            outcome=outcome,
            reason_code=reason_code,
            latency_ms=int((time.monotonic() - started) * 1000),
            adapter_version=self.adapter_version,
        )
