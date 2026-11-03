"""The AI gateway: one entry point for every AI task (DFR1-015).

Order of checks, each one denying before the next runs:

1. The request is well formed (bounds, schema).
2. The task type has an adapter in this release.
3. The organization has a route for the task (provider and model chosen by the organization).
4. The shared execution gate allows it: entitlement, organization switches, provider readiness, actor permission,
   consent, rate, and budget. The budget is reserved here, through the gate's ticket.
5. The provider credential is resolved for the organization only, and the call is made with a bounded timeout and a
   bounded number of attempts. Only transient failures are retried.
6. Actual usage is settled against the reservation. A failed call with no usage releases the whole reservation.
7. For structured output, the provider's text must match the schema, or the result is refused.

Nothing is returned that the provider did not produce. A refusal or failure carries a reason code and no content.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.ai_gateway.adapters import (
    CallOutcome,
    GatewayAdapter,
    ProviderCall,
    adapter_for,
)
from app.ai_gateway.contracts import (
    MAX_EMBEDDING_INPUTS,
    MAX_INPUT_CHARACTERS,
    MAX_OUTPUT_TOKENS,
    REASON_CREDENTIAL_UNAVAILABLE,
    REASON_INVALID_OUTPUT,
    REASON_INVALID_REQUEST,
    REASON_NO_ROUTE,
    REASON_OK,
    REASON_TASK_NOT_SUPPORTED,
    REASON_USAGE_SETTLEMENT_FAILED,
    GatewayRequest,
    TaskResult,
)
from app.ai_gateway.routing import Route, resolve_route
from app.ai_gateway.structured import parse_structured, validate_schema
from app.ai_gateway.tasks import IMPLEMENTED_TASKS, TaskType
from app.config import get_settings
from app.governance.execution_gate import (
    ExecutionRequest,
    evaluate_execution,
    release_ticket,
    settle_ticket,
)
from app.governance.usage_ledger import UsageError
from app.provider_secrets.errors import (
    ProviderSecretsConfigurationError,
    ProviderSecretsDecryptionError,
)
from app.provider_secrets.service import (
    NoActiveCredentialError,
    UnsupportedProviderError,
    get_provider_secret_for_gateway,
)

Sleep = Callable[[float], None]
_BACKOFF_STEP_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 2.0


def execute(db: Session, request: GatewayRequest, *, sleep: Sleep = time.sleep) -> TaskResult:
    """Run one AI task. The caller commits or rolls back the session, which settles or releases the reservation."""
    if request.task not in IMPLEMENTED_TASKS:
        return _refused(REASON_TASK_NOT_SUPPORTED)
    problem = _validate(request)
    if problem is not None:
        return _refused(REASON_INVALID_REQUEST)

    route = resolve_route(db, organization_id=request.organization_id, task=request.task)
    if route is None:
        return _refused(REASON_NO_ROUTE)

    settings = get_settings()
    adapter = adapter_for(
        route.provider_key,
        live_enabled=settings.provider_live_adapters_enabled,
        timeout_seconds=settings.ai_gateway_timeout_seconds,
    )
    if adapter is None or not adapter.supports(request.task):
        return _refused(REASON_TASK_NOT_SUPPORTED, route=route)

    decision = evaluate_execution(
        db,
        ExecutionRequest(
            organization_id=request.organization_id,
            capability_key=request.capability_key,
            user_context=request.user_context,
            resource_id=request.resource_id,
            budget_units=_budget_units(request),
        ),
    )
    if not decision.allowed or decision.ticket is None:
        return TaskResult(
            outcome="denied",
            reason_code=decision.reason_code,
            provider_key=route.provider_key,
            model=route.model,
        )
    ticket = decision.ticket

    try:
        secret = get_provider_secret_for_gateway(
            db,
            organization_id=request.organization_id,
            provider_key=route.provider_key,
        )
    except (
        NoActiveCredentialError,
        UnsupportedProviderError,
        ProviderSecretsConfigurationError,
        ProviderSecretsDecryptionError,
    ):
        release_ticket(db, ticket)
        return _failed(REASON_CREDENTIAL_UNAVAILABLE, route=route)

    try:
        call, attempts = _call_with_retries(adapter, request, route, secret.reveal(), sleep)
    finally:
        del secret

    if call.outcome is not CallOutcome.SUCCEEDED and not call.usage:
        release_ticket(db, ticket)
        return _failed(call.reason_code or REASON_INVALID_OUTPUT, route=route, attempts=attempts)

    try:
        settle_ticket(db, ticket, actual=call.usage)
    except UsageError:
        # The provider has answered, but its usage cannot be recorded against the reservation. The answer is withheld,
        # so nothing is returned that was not metered. The caller must roll back this session.
        return _failed(REASON_USAGE_SETTLEMENT_FAILED, route=route, attempts=attempts)

    if call.outcome is not CallOutcome.SUCCEEDED:
        return _failed(call.reason_code or REASON_INVALID_OUTPUT, route=route, attempts=attempts, usage=call.usage)

    if request.task is TaskType.TEXT and request.output_schema is not None:
        structured = parse_structured(call.text or "", request.output_schema)
        if structured is None:
            return _failed(REASON_INVALID_OUTPUT, route=route, attempts=attempts, usage=call.usage)
        return TaskResult(
            outcome="succeeded",
            reason_code=REASON_OK,
            provider_key=route.provider_key,
            model=route.model,
            structured=structured,
            usage=call.usage,
            attempts=attempts,
        )

    return TaskResult(
        outcome="succeeded",
        reason_code=REASON_OK,
        provider_key=route.provider_key,
        model=route.model,
        text=call.text,
        vectors=call.vectors,
        usage=call.usage,
        attempts=attempts,
    )


def _validate(request: GatewayRequest) -> str | None:
    if not request.capability_key.startswith("ai."):
        return "The capability must be an AI capability."
    if request.task is TaskType.TEXT:
        if request.texts or request.text is None or not request.text.strip():
            return "A text task needs one non-empty prompt."
        if len(request.text) > MAX_INPUT_CHARACTERS:
            return "The prompt is longer than the gateway accepts."
        if not 1 <= request.max_output_tokens <= MAX_OUTPUT_TOKENS:
            return "The output token limit is out of range."
        if request.input_token_estimate < 0:
            return "The input token estimate must not be negative."
        if request.output_schema is not None:
            return validate_schema(request.output_schema)
        return None
    if request.task is TaskType.EMBEDDING:
        if request.text is not None or request.output_schema is not None:
            return "An embedding task takes inputs only."
        if not 1 <= len(request.texts) <= MAX_EMBEDDING_INPUTS:
            return "An embedding task needs between one and the maximum number of inputs."
        if any(not item.strip() or len(item) > MAX_INPUT_CHARACTERS for item in request.texts):
            return "Each embedding input must be non-empty and within the length limit."
        if request.input_token_estimate < 1:
            return "An embedding task must declare its input token estimate."
        return None
    return "This task type is not supported."


def _budget_units(request: GatewayRequest) -> tuple[tuple[str, int], ...]:
    """The reservations taken before the call. The provider's reported usage replaces them when it settles."""
    units: list[tuple[str, int]] = []
    if request.task is TaskType.TEXT:
        units.append(("tokens_output", request.max_output_tokens))
    if request.input_token_estimate > 0:
        units.append(("tokens_input", request.input_token_estimate))
    return tuple(units)


def _call_with_retries(
    adapter: GatewayAdapter,
    request: GatewayRequest,
    route: Route,
    api_key: str,
    sleep: Sleep,
) -> tuple[ProviderCall, int]:
    max_attempts = get_settings().ai_gateway_max_attempts
    attempts = 0
    while True:
        attempts += 1
        call = _invoke(adapter, request, route, api_key)
        if call.outcome in (CallOutcome.SUCCEEDED, CallOutcome.PERMANENT) or attempts >= max_attempts:
            return call, attempts
        sleep(min(_BACKOFF_STEP_SECONDS * attempts, _BACKOFF_CAP_SECONDS))


def _invoke(adapter: GatewayAdapter, request: GatewayRequest, route: Route, api_key: str) -> ProviderCall:
    if request.task is TaskType.TEXT:
        return adapter.run_text(
            model=route.model,
            prompt=request.text or "",
            max_output_tokens=request.max_output_tokens,
            api_key=api_key,
        )
    return adapter.run_embedding(model=route.model, inputs=request.texts, api_key=api_key)


def _refused(reason: str, *, route: Route | None = None) -> TaskResult:
    return TaskResult(
        outcome="denied",
        reason_code=reason,
        provider_key=route.provider_key if route else None,
        model=route.model if route else None,
    )


def _failed(
    reason: str,
    *,
    route: Route,
    attempts: int = 0,
    usage: dict[str, int] | None = None,
) -> TaskResult:
    return TaskResult(
        outcome="failed",
        reason_code=reason,
        provider_key=route.provider_key,
        model=route.model,
        usage=dict(usage or {}),
        attempts=attempts,
    )


__all__ = ["execute"]
