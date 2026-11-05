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

import json
import time
import uuid
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_gateway.adapters import (
    CallOutcome,
    GatewayAdapter,
    ProviderCall,
    adapter_for,
)
from app.ai_gateway.contracts import (
    ALLOWED_IMAGE_TYPES,
    MAX_EMBEDDING_INPUTS,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_REQUEST,
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
    image_matches_type,
)
from app.ai_gateway.routing import Route, resolve_route
from app.ai_gateway.structured import parse_structured, validate_schema
from app.ai_gateway.tasks import IMPLEMENTED_TASKS, TaskType
from app.audit.attribution import user_attribution
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.config import get_settings
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.governance.ai_pricing import record_provider_costs
from app.governance.execution_gate import (
    ExecutionRequest,
    evaluate_execution,
    release_ticket,
    settle_ticket,
)
from app.governance.usage_ledger import UsageAttribution, UsageError
from app.provider_secrets.errors import (
    ProviderSecretsConfigurationError,
    ProviderSecretsDecryptionError,
)
from app.provider_secrets.service import (
    NoActiveCredentialError,
    UnsupportedProviderError,
    get_provider_secret_for_gateway,
)

GATEWAY_AUDIT_EVENT = "ai_gateway"
GATEWAY_EXECUTE_ACTION = "ai_gateway.execute"

Sleep = Callable[[float], None]
_BACKOFF_STEP_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 2.0


REASON_USAGE_ALREADY_RECORDED = "usage_already_recorded"


def execute(db: Session, request: GatewayRequest, *, sleep: Sleep = time.sleep) -> TaskResult:
    """Run one AI task. The caller commits or rolls back the session, which settles or releases the reservation.

    The primary route is tried first. The fallback route, when the organization has set one, is tried only after a transient
    failure (an unavailable provider, a timeout, or a missing credential). A permanent failure, such as a rejected credential
    or an unusable response, stops the task, because another provider would hit the same fault or would be asked to answer a
    request the first one refused.
    """
    if request.task not in IMPLEMENTED_TASKS:
        return _refused(REASON_TASK_NOT_SUPPORTED)
    problem = _validate(request)
    if problem is not None:
        return _refused(REASON_INVALID_REQUEST)

    route = resolve_route(db, organization_id=request.organization_id, task=request.task)
    if route is None:
        return _refused(REASON_NO_ROUTE)

    settings = get_settings()
    candidates: list[tuple[str, str, GatewayAdapter]] = []
    for provider_key, model in route.candidates():
        adapter = adapter_for(
            provider_key,
            live_enabled=settings.provider_live_adapters_enabled,
            timeout_seconds=settings.ai_gateway_timeout_seconds,
        )
        if adapter is not None and adapter.supports(request.task):
            candidates.append((provider_key, model, adapter))
    if not candidates:
        return _refused(REASON_TASK_NOT_SUPPORTED, route=route)

    # A call that an agent or workflow already metered is not sent to the provider again.
    if (
        request.attribution is not None
        and request.attribution.call_key is not None
        and _already_recorded(db, request.organization_id, request.attribution.call_key)
    ):
        return TaskResult(outcome="denied", reason_code=REASON_USAGE_ALREADY_RECORDED,
                          provider_key=route.provider_key, model=route.model)
    decision = evaluate_execution(
        db,
        ExecutionRequest(
            organization_id=request.organization_id,
            capability_key=request.capability_key,
            user_context=request.user_context,
            resource_id=request.resource_id,
            # Each call reserves under its own key. A shared key would make every later call for the same capability conflict.
            idempotency_key=_call_key(request),
            budget_units=_budget_units(request),
            attribution=_reserve_attribution(request, route.provider_key, route.model),
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

    # The requested record is committed before any provider is contacted. If it cannot be written, the exception propagates,
    # no call is made, and the caller rolls back the reservation.
    requested = _record_requested(db, request, candidates[0][0], candidates[0][1])

    call, provider_key, model, attempts = _run_candidates(db, request, candidates, sleep)
    if call is None:
        release_ticket(db, ticket)
        result = _failed(REASON_CREDENTIAL_UNAVAILABLE, route=route, attempts=attempts,
                         provider_key=provider_key, model=model)
        _record_completed(db, request, requested, result, provider_key=provider_key, model=model)
        return result

    if call.outcome is not CallOutcome.SUCCEEDED and not call.usage:
        release_ticket(db, ticket)
        result = _failed(call.reason_code or REASON_INVALID_OUTPUT, route=route, attempts=attempts,
                         provider_key=provider_key, model=model)
        _record_completed(db, request, requested, result, provider_key=provider_key, model=model)
        return result

    try:
        events = settle_ticket(db, ticket, actual=_actual_usage(call.usage, request), provider=provider_key, model=model)
        record_provider_costs(db, organization_id=request.organization_id, events=events,
                              provider_key=provider_key, model=model)
    except UsageError:
        # The provider has answered, but its usage cannot be recorded against the reservation. The answer is withheld,
        # so nothing is returned that was not metered. The caller must roll back this session.
        result = _failed(REASON_USAGE_SETTLEMENT_FAILED, route=route, attempts=attempts,
                         provider_key=provider_key, model=model)
        _record_completed(db, request, requested, result, provider_key=provider_key, model=model)
        return result

    result = _final_result(request, call, provider_key, model, attempts)
    _record_completed(db, request, requested, result, provider_key=provider_key, model=model)
    return result


def _run_candidates(
    db: Session,
    request: GatewayRequest,
    candidates: list[tuple[str, str, GatewayAdapter]],
    sleep: Sleep,
) -> tuple[ProviderCall | None, str, str, int]:
    """Try each candidate in order. Returns the call that ends the task, the provider and model that made it, and attempts.

    The call is None when no candidate had a usable credential, so no provider was contacted.
    """
    total_attempts = 0
    last_call: ProviderCall | None = None
    last_provider, last_model = candidates[0][0], candidates[0][1]
    for provider_key, model, adapter in candidates:
        last_provider, last_model = provider_key, model
        try:
            secret = get_provider_secret_for_gateway(
                db,
                organization_id=request.organization_id,
                provider_key=provider_key,
            )
        except (
            NoActiveCredentialError,
            UnsupportedProviderError,
            ProviderSecretsConfigurationError,
            ProviderSecretsDecryptionError,
        ):
            continue
        try:
            call, attempts = _call_with_retries(adapter, request, model, secret.reveal(), sleep)
        finally:
            del secret
        total_attempts += attempts
        last_call = call
        if call.outcome in (CallOutcome.SUCCEEDED, CallOutcome.PERMANENT):
            return call, provider_key, model, total_attempts
    return last_call, last_provider, last_model, total_attempts


def _final_result(
    request: GatewayRequest,
    call: ProviderCall,
    provider_key: str,
    model: str,
    attempts: int,
) -> TaskResult:
    if call.outcome is not CallOutcome.SUCCEEDED:
        return _failed(call.reason_code or REASON_INVALID_OUTPUT, route=None, attempts=attempts,
                       usage=call.usage, provider_key=provider_key, model=model)
    if request.task in (TaskType.TEXT, TaskType.MULTIMODAL) and request.output_schema is not None:
        structured = parse_structured(call.text or "", request.output_schema)
        if structured is None:
            return _failed(REASON_INVALID_OUTPUT, route=None, attempts=attempts, usage=call.usage,
                           provider_key=provider_key, model=model)
        return TaskResult(
            outcome="succeeded",
            reason_code=REASON_OK,
            provider_key=provider_key,
            model=model,
            structured=structured,
            usage=call.usage,
            attempts=attempts,
        )
    return TaskResult(
        outcome="succeeded",
        reason_code=REASON_OK,
        provider_key=provider_key,
        model=model,
        text=call.text,
        vectors=call.vectors,
        usage=call.usage,
        attempts=attempts,
    )


def _record_requested(db: Session, request: GatewayRequest, provider_key: str, model: str) -> AuditEvent:
    """Commit the requested record in its own transaction, so it survives a rollback of the business work (WP3)."""
    return persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=request.organization_id,
                                     actor_user_id=request.user_context.user.id),
        event_type=GATEWAY_AUDIT_EVENT,
        action=GATEWAY_EXECUTE_ACTION,
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key=None,
        resource_type="ai_task",
        resource_id=request.task.value,
        correlation_id=str(uuid.uuid4()),
        metadata={"task": request.task.value, "capability_key": request.capability_key,
                  "provider_key": provider_key, "model": model},
    )


def _record_completed(
    db: Session,
    request: GatewayRequest,
    requested: AuditEvent,
    result: TaskResult,
    *,
    provider_key: str,
    model: str,
) -> None:
    """The completed record follows the requested record in the caller's transaction. It holds numbers and codes only,
    never the prompt, the output, or the credential."""
    payload = {
        "task": request.task.value,
        "provider_key": provider_key,
        "model": model,
        "outcome": result.outcome,
        "reason_code": result.reason_code,
        "attempts": result.attempts,
        "usage": dict(result.usage),
    }
    db.add(
        AuditEvent(
            user_id=request.user_context.user.id,
            organization_id=request.organization_id,
            event_type=GATEWAY_AUDIT_EVENT,
            action=GATEWAY_EXECUTE_ACTION,
            decision="allowed" if result.outcome == "succeeded" else "denied",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            correlation_id=requested.correlation_id,
            permission_key=None,
            resource_type="ai_task",
            resource_id=request.task.value,
            event_metadata=json.dumps(payload, sort_keys=True, default=str),
        )
    )
    db.flush()


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
        if request.images:
            return "A text task takes no images."
        if request.output_schema is not None:
            return validate_schema(request.output_schema)
        return None
    if request.task is TaskType.MULTIMODAL:
        return _validate_multimodal(request)
    if request.task is TaskType.EMBEDDING:
        if request.text is not None or request.output_schema is not None or request.images:
            return "An embedding task takes inputs only."
        if not 1 <= len(request.texts) <= MAX_EMBEDDING_INPUTS:
            return "An embedding task needs between one and the maximum number of inputs."
        if any(not item.strip() or len(item) > MAX_INPUT_CHARACTERS for item in request.texts):
            return "Each embedding input must be non-empty and within the length limit."
        if request.input_token_estimate < 1:
            return "An embedding task must declare its input token estimate."
        return None
    return "This task type is not supported."


def _validate_multimodal(request: GatewayRequest) -> str | None:
    """A multimodal task is one prompt, one to the maximum number of images, and a structured output. Image bytes must
    match the stated type, so a file cannot be sent to a provider under a type it does not have."""
    if request.texts or request.text is None or not request.text.strip():
        return "A multimodal task needs one non-empty prompt."
    if len(request.text) > MAX_INPUT_CHARACTERS:
        return "The prompt is longer than the gateway accepts."
    if not 1 <= request.max_output_tokens <= MAX_OUTPUT_TOKENS:
        return "The output token limit is out of range."
    if request.input_token_estimate < 1:
        return "A multimodal task must declare its input token estimate."
    if request.output_schema is None:
        return "A multimodal task needs a structured output schema."
    problem = validate_schema(request.output_schema)
    if problem is not None:
        return problem
    if not 1 <= len(request.images) <= MAX_IMAGES_PER_REQUEST:
        return "A multimodal task needs between one and the maximum number of images."
    for image in request.images:
        if image.mime_type not in ALLOWED_IMAGE_TYPES:
            return "Only PNG and JPEG images are accepted."
        if not image.data or len(image.data) > MAX_IMAGE_BYTES:
            return "Each image must be non-empty and within the size limit."
        if not image_matches_type(image.mime_type, image.data):
            return "An image's bytes do not match its stated type."
    return None


def _call_key(request: GatewayRequest) -> str:
    """The idempotency key for this call. An agent or workflow call names its own key, so a repeat shares one usage entry."""
    if request.attribution is not None and request.attribution.call_key is not None:
        return request.attribution.call_key
    return str(uuid.uuid4())


def _already_recorded(db: Session, organization_id: UUID, call_key: str) -> bool:
    """True when usage for this call key is already recorded."""
    return db.scalar(select(AiUsageEvent.id).where(
        AiUsageEvent.organization_id == organization_id,
        AiUsageEvent.idempotency_key.like(f"{call_key}:%"),
        AiUsageEvent.status == AiUsageEvent.STATUS_RECORDED,
    ).limit(1)) is not None


def _actual_usage(usage: dict[str, int], request: GatewayRequest) -> dict[str, int]:
    """The provider's usage, plus the pages this call read. Pages come from the request, never from images."""
    actual = dict(usage)
    if request.document_pages > 0:
        actual["document_pages"] = request.document_pages
    return actual


def _reserve_attribution(request: GatewayRequest, provider_key: str, model: str) -> UsageAttribution:
    """The attribution known before the call. The provider and model are the planned route; settlement records the one that answered."""
    base = request.attribution or UsageAttribution()
    return UsageAttribution(
        agent_id=base.agent_id,
        workflow_id=base.workflow_id,
        execution_id=base.execution_id,
        task_type=request.task.value,
        workflow_step_id=base.workflow_step_id,
        call_key=base.call_key,
        provider=provider_key,
        model=model,
    )


def _budget_units(request: GatewayRequest) -> tuple[tuple[str, int], ...]:
    """The reservations taken before the call. The provider's reported usage replaces them when it settles."""
    units: list[tuple[str, int]] = []
    if request.task is TaskType.TEXT:
        units.append(("tokens_output", request.max_output_tokens))
    if request.task is TaskType.MULTIMODAL:
        units.append(("tokens_output", request.max_output_tokens))
        units.append(("images", len(request.images)))
    if request.input_token_estimate > 0:
        units.append(("tokens_input", request.input_token_estimate))
    if request.document_pages > 0:
        units.append(("document_pages", request.document_pages))
    return tuple(units)


def _call_with_retries(
    adapter: GatewayAdapter,
    request: GatewayRequest,
    model: str,
    api_key: str,
    sleep: Sleep,
) -> tuple[ProviderCall, int]:
    """Make one candidate's call, retrying only transient failures, up to the configured number of attempts."""
    max_attempts = get_settings().ai_gateway_max_attempts
    attempts = 0
    while True:
        attempts += 1
        call = _invoke(adapter, request, model, api_key)
        if call.outcome in (CallOutcome.SUCCEEDED, CallOutcome.PERMANENT) or attempts >= max_attempts:
            return call, attempts
        sleep(min(_BACKOFF_STEP_SECONDS * attempts, _BACKOFF_CAP_SECONDS))


def _invoke(adapter: GatewayAdapter, request: GatewayRequest, model: str, api_key: str) -> ProviderCall:
    if request.task is TaskType.TEXT:
        return adapter.run_text(
            model=model,
            prompt=request.text or "",
            max_output_tokens=request.max_output_tokens,
            api_key=api_key,
        )
    if request.task is TaskType.MULTIMODAL:
        return adapter.run_multimodal(
            model=model,
            prompt=request.text or "",
            images=request.images,
            max_output_tokens=request.max_output_tokens,
            api_key=api_key,
        )
    return adapter.run_embedding(model=model, inputs=request.texts, api_key=api_key)


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
    route: Route | None,
    attempts: int = 0,
    usage: dict[str, int] | None = None,
    provider_key: str | None = None,
    model: str | None = None,
) -> TaskResult:
    """A failed result. The provider and model are the ones that were tried, when known."""
    return TaskResult(
        outcome="failed",
        reason_code=reason,
        provider_key=provider_key or (route.provider_key if route else None),
        model=model or (route.model if route else None),
        usage=dict(usage or {}),
        attempts=attempts,
    )


__all__ = ["execute"]
