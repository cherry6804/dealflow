"""Provider adapters for AI tasks (DFR1-015, ADR-0032 decision D1).

An adapter turns one task into one provider call and classifies the result. It never retries (the service does that, within
a bound), never logs or stores a response body, and never reads more of a response than the output it returns.

Live access is controlled by ``PROVIDER_LIVE_ADAPTERS_ENABLED``, which is off by default and not enabled in CI. With the
flag off, an adapter refuses without making a network call. Tests use an httpx mock transport, so no test contacts a
provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import httpx

from app.ai_gateway.contracts import (
    REASON_LIVE_DISABLED,
    REASON_PROVIDER_REJECTED,
    REASON_PROVIDER_RESPONSE,
    REASON_PROVIDER_TIMEOUT,
    REASON_PROVIDER_UNAVAILABLE,
)
from app.ai_gateway.tasks import TaskType

OPENAI_PROVIDER_KEY = "openai"
OPENAI_ADAPTER_VERSION = "openai-gateway-v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
_REJECTED_STATUSES = frozenset({401, 403})


class CallOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    TRANSIENT = "transient"  # Retryable: network failure, 429, 5xx, or a timeout.
    TIMED_OUT = "timed_out"  # Retryable within the bound.
    PERMANENT = "permanent"  # Not retryable: refused, rejected, disabled, or an unusable response.


@dataclass(frozen=True)
class ProviderCall:
    outcome: CallOutcome
    reason_code: str | None = None
    text: str | None = None
    vectors: tuple[tuple[float, ...], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    adapter_version: str = ""


class GatewayAdapter(Protocol):
    provider_key: str
    adapter_version: str

    def supports(self, task: TaskType) -> bool: ...

    def run_text(self, *, model: str, prompt: str, max_output_tokens: int, api_key: str) -> ProviderCall: ...

    def run_embedding(self, *, model: str, inputs: tuple[str, ...], api_key: str) -> ProviderCall: ...


class OpenAIGatewayAdapter:
    provider_key = OPENAI_PROVIDER_KEY
    adapter_version = OPENAI_ADAPTER_VERSION

    def __init__(
        self,
        *,
        live_enabled: bool,
        timeout_seconds: float,
        base_url: str = OPENAI_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._live_enabled = live_enabled
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def supports(self, task: TaskType) -> bool:
        return task in (TaskType.TEXT, TaskType.EMBEDDING)

    def run_text(self, *, model: str, prompt: str, max_output_tokens: int, api_key: str) -> ProviderCall:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_output_tokens,
        }
        decoded = self._post("/chat/completions", body, api_key)
        if isinstance(decoded, ProviderCall):
            return decoded
        try:
            text = decoded["choices"][0]["message"]["content"]
            usage = decoded["usage"]
            if not isinstance(text, str):
                raise TypeError("content is not text")
            return ProviderCall(
                outcome=CallOutcome.SUCCEEDED,
                text=text,
                usage={
                    "tokens_input": _count(usage, "prompt_tokens"),
                    "tokens_output": _count(usage, "completion_tokens"),
                },
                adapter_version=self.adapter_version,
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return self._unusable()

    def run_embedding(self, *, model: str, inputs: tuple[str, ...], api_key: str) -> ProviderCall:
        decoded = self._post("/embeddings", {"model": model, "input": list(inputs)}, api_key)
        if isinstance(decoded, ProviderCall):
            return decoded
        try:
            rows = sorted(decoded["data"], key=lambda row: int(row["index"]))
            vectors = tuple(tuple(float(value) for value in row["embedding"]) for row in rows)
            if len(vectors) != len(inputs):
                raise ValueError("vector count does not match input count")
            return ProviderCall(
                outcome=CallOutcome.SUCCEEDED,
                vectors=vectors,
                usage={"tokens_input": _count(decoded["usage"], "prompt_tokens")},
                adapter_version=self.adapter_version,
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return self._unusable()

    def _post(self, path: str, body: dict[str, object], api_key: str) -> dict[str, object] | ProviderCall:
        if not self._live_enabled:
            return ProviderCall(
                outcome=CallOutcome.PERMANENT,
                reason_code=REASON_LIVE_DISABLED,
                adapter_version=self.adapter_version,
            )
        try:
            with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = client.post(
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
        except httpx.TimeoutException:
            return ProviderCall(outcome=CallOutcome.TIMED_OUT, reason_code=REASON_PROVIDER_TIMEOUT,
                                adapter_version=self.adapter_version)
        except httpx.HTTPError:
            return ProviderCall(outcome=CallOutcome.TRANSIENT, reason_code=REASON_PROVIDER_UNAVAILABLE,
                                adapter_version=self.adapter_version)

        status_code = response.status_code
        if 200 <= status_code < 300:
            try:
                decoded = response.json()
            except ValueError:
                return self._unusable()
            if not isinstance(decoded, dict):
                return self._unusable()
            return decoded
        if status_code in _REJECTED_STATUSES:
            return ProviderCall(outcome=CallOutcome.PERMANENT, reason_code=REASON_PROVIDER_REJECTED,
                                adapter_version=self.adapter_version)
        if status_code == 429 or status_code >= 500:
            return ProviderCall(outcome=CallOutcome.TRANSIENT, reason_code=REASON_PROVIDER_UNAVAILABLE,
                                adapter_version=self.adapter_version)
        return self._unusable()

    def _unusable(self) -> ProviderCall:
        return ProviderCall(
            outcome=CallOutcome.PERMANENT,
            reason_code=REASON_PROVIDER_RESPONSE,
            adapter_version=self.adapter_version,
        )


def _count(usage: object, key: str) -> int:
    if not isinstance(usage, dict):
        raise TypeError("usage is not an object")
    value = usage[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("usage count is not a non-negative integer")
    return value


def adapter_for(provider_key: str, *, live_enabled: bool, timeout_seconds: float) -> GatewayAdapter | None:
    """The adapter for a provider key, or None when no gateway adapter exists for it."""
    if provider_key == OPENAI_PROVIDER_KEY:
        return OpenAIGatewayAdapter(live_enabled=live_enabled, timeout_seconds=timeout_seconds)
    return None


__all__ = [
    "CallOutcome",
    "GatewayAdapter",
    "OpenAIGatewayAdapter",
    "ProviderCall",
    "adapter_for",
]
