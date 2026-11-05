"""Multimodal AI tasks for document review, through the AI gateway only (DFR1-035).

Every call goes through ``app.ai_gateway.service.execute``. The shared execution gate (entitlement and switches, provider
readiness, actor permission, rate, budget), the organization's route, credential resolution, the timeout, bounded retries and
audit all apply. This module adds no bypass. A refusal is returned with the gateway's own reason code.

Budget units reserved per call: output tokens, input tokens (estimated) and images. An organization without a budget for
images is refused with ``budget_not_configured``, so image work cannot run unmetered.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai_gateway.contracts import GatewayRequest, ImageInput, TaskResult
from app.ai_gateway.service import execute as gateway_execute
from app.ai_gateway.tasks import TaskType
from app.auth.dependencies import CurrentUserContext
from app.knowledge.service import CAPABILITY

# Reserved per image before the call. The provider's reported usage replaces the reservation when the call settles.
IMAGE_TOKEN_ESTIMATE = 1_500

Sleep = Callable[[float], None]


def run_multimodal(
    db: Session,
    *,
    organization_id: UUID,
    user_context: CurrentUserContext,
    prompt: str,
    images: tuple[ImageInput, ...],
    schema: dict[str, str],
    max_output_tokens: int,
    document_pages: int = 0,
    sleep: Sleep = time.sleep,
) -> TaskResult:
    """Run one prompt over one or more images, with a structured output. The caller commits or rolls back the session."""
    estimate = len(prompt) // 4 + 1 + IMAGE_TOKEN_ESTIMATE * len(images)
    return gateway_execute(
        db,
        GatewayRequest(
            organization_id=organization_id,
            capability_key=CAPABILITY,
            task=TaskType.MULTIMODAL,
            user_context=user_context,
            text=prompt,
            images=images,
            output_schema=schema,
            max_output_tokens=max_output_tokens,
            input_token_estimate=estimate,
            document_pages=document_pages,
        ),
        sleep=sleep,
    )
