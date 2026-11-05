"""Request and result contracts for the AI gateway (DFR1-015).

Results are either real provider output or a stable refusal or failure code. Nothing here fabricates an answer: when a
provider is unavailable, the result says so and carries no content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.ai_gateway.tasks import TaskType
from app.auth.dependencies import CurrentUserContext
from app.governance.usage_ledger import UsageAttribution

Outcome = Literal["succeeded", "denied", "failed"]

# Largest prompt or embedding input the gateway accepts, in characters. A bound keeps one request from metering an
# unbounded amount before the budget is checked.
MAX_INPUT_CHARACTERS = 32_000
MAX_OUTPUT_TOKENS = 4_096
MAX_EMBEDDING_INPUTS = 64
# Images sent with one multimodal request. A page scan is one image, so this bounds the pages in one call.
MAX_IMAGES_PER_REQUEST = 1
MAX_IMAGE_BYTES = 8_000_000
ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg"})
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"

# Stable reason codes. Callers branch on these, never on message text.
REASON_OK = "ok"
REASON_INVALID_REQUEST = "invalid_request"
REASON_TASK_NOT_SUPPORTED = "task_not_supported"
REASON_NO_ROUTE = "no_route_configured"
REASON_CREDENTIAL_UNAVAILABLE = "credential_unavailable"
REASON_LIVE_DISABLED = "live_adapter_disabled"
REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
REASON_PROVIDER_TIMEOUT = "provider_timeout"
REASON_PROVIDER_REJECTED = "provider_rejected_credential"
REASON_PROVIDER_RESPONSE = "unexpected_provider_response"
REASON_INVALID_OUTPUT = "invalid_structured_output"
REASON_USAGE_SETTLEMENT_FAILED = "usage_settlement_failed"


@dataclass(frozen=True)
class ImageInput:
    """One image sent with a multimodal task. The bytes are never part of a repr, so they cannot reach a log by accident."""

    mime_type: str
    data: bytes = field(repr=False)


def image_matches_type(mime_type: str, data: bytes) -> bool:
    """True when the bytes start with the signature of the stated image type."""
    if mime_type == "image/png":
        return data.startswith(_PNG_SIGNATURE)
    if mime_type == "image/jpeg":
        return data.startswith(_JPEG_SIGNATURE)
    return False


@dataclass(frozen=True)
class GatewayRequest:
    """One AI task, run under one named capability so the gate can check that capability.

    ``output_schema`` maps each required key to a JSON type name (``string``, ``number``, ``integer``, ``boolean``,
    ``array`` or ``object``). Keys outside the schema are refused.
    """

    organization_id: UUID
    capability_key: str
    task: TaskType
    user_context: CurrentUserContext
    text: str | None = None
    texts: tuple[str, ...] = ()
    max_output_tokens: int = 256
    input_token_estimate: int = 0
    output_schema: dict[str, str] | None = None
    resource_id: str | None = None
    images: tuple[ImageInput, ...] = ()
    # Agent, workflow and execution that caused this call, when there is one. Provider and model are filled in by the gateway.
    attribution: UsageAttribution | None = None


@dataclass(frozen=True)
class TaskResult:
    outcome: Outcome
    reason_code: str
    provider_key: str | None = None
    model: str | None = None
    text: str | None = None
    structured: dict[str, object] | None = None
    vectors: tuple[tuple[float, ...], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    attempts: int = 0

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded"
