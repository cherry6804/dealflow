"""AI gateway (DFR1-015): adapters, structured output, the execution path, usage, tenant isolation and route management.

Provider calls go through an httpx mock transport. No test contacts a provider, and no test returns a provider answer that the
mock did not produce.

Test-only seams, each documented where it is used:

- ``allow_provider_readiness``: a verified connection is not created here (verification needs a live provider), so the
  provider gate is passed by patching readiness. The credential itself is real: it is stored through the encrypted path.
- ``allow_actor_execution_permission``: the AI actor key is pending approval (see ``e13-ai-actor-permission-proposal.md``),
  so tests grant the owner a catalogued key instead.
- ``_allow_rate_for_tests``: no rate rule is approved for AI capabilities. Production therefore denies AI execution at the
  rate gate.
- ``_allow_resource_for_tests``: no AI resource store exists, so the resource gate denies every AI capability with
  ``resource_not_found``, even when a resource is named. Tests patch that one gate. Production denial is asserted in
  ``test_production_layers_deny_in_order``.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.ai_gateway import service as gateway
from app.ai_gateway.adapters import CallOutcome, OpenAIGatewayAdapter
from app.ai_gateway.contracts import GatewayRequest
from app.ai_gateway.routing import InvalidRouteError, set_route
from app.ai_gateway.structured import parse_structured, validate_schema
from app.ai_gateway.tasks import TaskType
from app.api.ai_gateway import router as ai_gateway_router
from app.auth.dependencies import CurrentUserContext
from app.config import get_settings
from app.db.models.ai_pricing import AiProviderCostEntry
from app.db.models.ai_task_route import AiTaskRoute
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_credential import ProviderCredential
from app.db.session import SessionLocal, get_db_session
from app.governance import execution_gate
from app.governance.capabilities import AI_MASTER
from app.governance.execution_gate import GateOutcome
from app.governance.service import set_capability_enabled
from app.governance.usage_ledger import UsageUnit, configure_budget
from app.providers import service as connections
from app.tenant.dependencies import TenantContext, get_tenant_context
from tests.governance_helpers import (
    allow_actor_execution_permission,
    allow_organization_entitlements,
    allow_provider_readiness,
)
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

CAPABILITY = "ai.assistant"
SECRET_PREFIX = "sk-gateway-"
TEST_RATE_TYPE = "ai_gateway_test"


# --- fixtures and helpers -----------------------------------------------------------------------


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


@pytest.fixture
def keyring(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "test-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"test-v1": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def live_settings(monkeypatch, keyring) -> Iterator[None]:
    monkeypatch.setenv("PROVIDER_LIVE_ADAPTERS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _cleanup(organization_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(AiProviderCostEntry).where(AiProviderCostEntry.organization_id == organization_id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization_id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        db.execute(delete(AiTaskRoute).where(AiTaskRoute.organization_id == organization_id))
        db.execute(delete(ProviderConnection).where(ProviderConnection.organization_id == organization_id))
        db.execute(delete(ProviderCredential).where(ProviderCredential.organization_id == organization_id))
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


@pytest.fixture
def org(keyring) -> Iterator[tuple[uuid.UUID, object]]:
    user, organization = create_owner_manager(permissions=("governance.capabilities.manage",))
    yield organization.id, user
    _cleanup(organization.id)


@pytest.fixture
def enabled(org, monkeypatch):
    """Entitlement, switches, actor key and readiness passed; rate passed by the test seam; budgets configured."""
    organization_id, user = org
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    allow_actor_execution_permission(monkeypatch, "governance.consent.read")
    _allow_rate_for_tests(monkeypatch)
    _allow_resource_for_tests(monkeypatch)
    with SessionLocal() as db:
        for key in (AI_MASTER, CAPABILITY):
            set_capability_enabled(db, organization_id=organization_id, actor_user_id=user.id,
                                   capability_key=key, is_enabled=True)
        db.commit()
    return organization_id, user


def _allow_resource_for_tests(monkeypatch) -> None:
    def passed(db, request, outcomes):
        outcomes.append(GateOutcome(gate="resource", allowed=True, reason_code="allowed_all"))

    monkeypatch.setattr(execution_gate, "_gate_resource", passed)


def _allow_rate_for_tests(monkeypatch) -> None:
    monkeypatch.setitem(execution_gate.RATE_EXECUTION_TYPE, CAPABILITY, TEST_RATE_TYPE)
    monkeypatch.setattr(
        execution_gate,
        "consume_or_deny",
        lambda db, **kwargs: SimpleNamespace(allowed=True, reason_code="allowed"),
    )


def _configure_budgets(organization_id: uuid.UUID, *, output: int = 1000, inputs: int = 1000) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        configure_budget(db, organization_id=organization_id, unit=UsageUnit.TOKENS_OUTPUT,
                         limit_quantity=output, moment=now)
        configure_budget(db, organization_id=organization_id, unit=UsageUnit.TOKENS_INPUT,
                         limit_quantity=inputs, moment=now)
        db.commit()


def _store_credential(organization_id: uuid.UUID, user_id: uuid.UUID, secret: str) -> None:
    with SessionLocal() as db:
        connections.create_connection(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            provider_key="openai",
            label="Main",
            secret=secret,
        )
        db.commit()


def _set_route(organization_id: uuid.UUID, user_id: uuid.UUID, task: TaskType, model: str = "test-model") -> None:
    with SessionLocal() as db:
        set_route(db, organization_id=organization_id, actor_user_id=user_id, task=task,
                  provider_key="openai", model=model)
        db.commit()


def _usage_rows(organization_id: uuid.UUID) -> list[AiUsageEvent]:
    with SessionLocal() as db:
        rows = db.scalars(select(AiUsageEvent).where(AiUsageEvent.organization_id == organization_id)).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def _consumed(organization_id: uuid.UUID, unit: UsageUnit) -> int:
    with SessionLocal() as db:
        row = db.scalar(
            select(OrganizationUsageBudget).where(
                OrganizationUsageBudget.organization_id == organization_id,
                OrganizationUsageBudget.unit == unit.value,
            )
        )
        return 0 if row is None else row.consumed_quantity


class _Provider:
    """Scripted provider boundary. Each call pops the next response; an exception is raised instead."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.authorizations: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.authorizations.append(request.headers.get("authorization", ""))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok_text(content: str, *, prompt: int = 10, completion: int = 20) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion},
        },
    )


def _ok_embedding(vectors, *, prompt: int = 7) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [{"index": index, "embedding": vector} for index, vector in enumerate(vectors)],
            "usage": {"prompt_tokens": prompt, "total_tokens": prompt},
        },
    )


def _use_provider(monkeypatch, provider: _Provider, *, live: bool = True) -> None:
    transport = httpx.MockTransport(provider)

    def adapter(provider_key, *, live_enabled, timeout_seconds):
        return OpenAIGatewayAdapter(live_enabled=live and live_enabled, timeout_seconds=timeout_seconds,
                                    transport=transport)

    monkeypatch.setattr(gateway, "adapter_for", adapter)


def _no_sleep(seconds: float) -> None:
    return None


def _text_request(organization_id, user, *, schema=None, prompt="Summarise the lead.", max_tokens=50) -> GatewayRequest:
    return GatewayRequest(
        organization_id=organization_id,
        capability_key=CAPABILITY,
        task=TaskType.TEXT,
        user_context=CurrentUserContext(user=user),
        text=prompt,
        max_output_tokens=max_tokens,
        input_token_estimate=30,
        output_schema=schema,
    )


# --- adapter: real HTTP mapping through the mock transport --------------------------------------


def test_text_success_maps_content_and_usage_through_the_real_adapter() -> None:
    provider = _Provider(_ok_text("Hello", prompt=11, completion=4))
    adapter = OpenAIGatewayAdapter(live_enabled=True, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_text(model="m", prompt="hi", max_output_tokens=10, api_key="sk-live-value")

    assert call.outcome is CallOutcome.SUCCEEDED
    assert call.text == "Hello"
    assert call.usage == {"tokens_input": 11, "tokens_output": 4}
    assert provider.authorizations == ["Bearer sk-live-value"]


def test_embedding_success_orders_vectors_by_index() -> None:
    provider = _Provider(httpx.Response(200, json={
        "data": [{"index": 1, "embedding": [0.2, 0.3]}, {"index": 0, "embedding": [0.0, 0.1]}],
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }))
    adapter = OpenAIGatewayAdapter(live_enabled=True, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_embedding(model="m", inputs=("a", "b"), api_key="k")

    assert call.outcome is CallOutcome.SUCCEEDED
    assert call.vectors == ((0.0, 0.1), (0.2, 0.3))
    assert call.usage == {"tokens_input": 5}


@pytest.mark.parametrize(
    ("status", "outcome", "reason"),
    [
        (429, CallOutcome.TRANSIENT, "provider_unavailable"),
        (503, CallOutcome.TRANSIENT, "provider_unavailable"),
        (401, CallOutcome.PERMANENT, "provider_rejected_credential"),
        (403, CallOutcome.PERMANENT, "provider_rejected_credential"),
        (400, CallOutcome.PERMANENT, "unexpected_provider_response"),
    ],
)
def test_status_codes_are_classified_for_retry(status, outcome, reason) -> None:
    provider = _Provider(httpx.Response(status, text="body that must not be read"))
    adapter = OpenAIGatewayAdapter(live_enabled=True, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_text(model="m", prompt="x", max_output_tokens=5, api_key="k")
    assert call.outcome is outcome
    assert call.reason_code == reason
    assert call.text is None


def test_a_timeout_is_classified_as_timed_out() -> None:
    provider = _Provider(httpx.ReadTimeout("slow"))
    adapter = OpenAIGatewayAdapter(live_enabled=True, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_text(model="m", prompt="x", max_output_tokens=5, api_key="k")
    assert call.outcome is CallOutcome.TIMED_OUT
    assert call.reason_code == "provider_timeout"


def test_a_network_error_is_transient() -> None:
    provider = _Provider(httpx.ConnectError("refused"))
    adapter = OpenAIGatewayAdapter(live_enabled=True, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_text(model="m", prompt="x", max_output_tokens=5, api_key="k")
    assert call.outcome is CallOutcome.TRANSIENT


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": 5}}], "usage": {"prompt_tokens": 1,
                                                                                    "completion_tokens": 1}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "x"}}],
                                  "usage": {"prompt_tokens": -1, "completion_tokens": 1}}),
    ],
)
def test_unusable_success_bodies_are_refused_without_content(response) -> None:
    provider = _Provider(response)
    adapter = OpenAIGatewayAdapter(live_enabled=True, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_text(model="m", prompt="x", max_output_tokens=5, api_key="k")
    assert call.outcome is CallOutcome.PERMANENT
    assert call.reason_code == "unexpected_provider_response"
    assert call.text is None and call.usage == {}


def test_live_disabled_makes_no_network_call() -> None:
    provider = _Provider()  # any call would pop from an empty list and fail the test
    adapter = OpenAIGatewayAdapter(live_enabled=False, timeout_seconds=5, transport=httpx.MockTransport(provider))
    call = adapter.run_text(model="m", prompt="x", max_output_tokens=5, api_key="k")
    assert call.reason_code == "live_adapter_disabled"
    assert provider.calls == 0


# --- structured output ------------------------------------------------------------------------


def test_structured_output_accepts_exact_matching_objects() -> None:
    schema = {"summary": "string", "score": "number", "tags": "array"}
    assert parse_structured(json.dumps({"summary": "ok", "score": 0.5, "tags": []}), schema) == {
        "summary": "ok", "score": 0.5, "tags": []}


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[1, 2]",
        json.dumps({"summary": "ok", "score": 0.5}),  # missing key
        json.dumps({"summary": "ok", "score": 0.5, "tags": [], "extra": 1}),  # unknown key
        json.dumps({"summary": 1, "score": 0.5, "tags": []}),  # wrong type
        json.dumps({"summary": "ok", "score": True, "tags": []}),  # bool is not a number
    ],
)
def test_structured_output_refuses_anything_else(text) -> None:
    assert parse_structured(text, {"summary": "string", "score": "number", "tags": "array"}) is None


def test_integer_type_refuses_booleans_and_floats() -> None:
    assert parse_structured(json.dumps({"n": True}), {"n": "integer"}) is None
    assert parse_structured(json.dumps({"n": 1.5}), {"n": "integer"}) is None
    assert parse_structured(json.dumps({"n": 2}), {"n": "integer"}) == {"n": 2}


def test_schema_validation_rejects_unknown_types_and_empty_schemas() -> None:
    assert validate_schema({}) is not None
    assert validate_schema({"x": "dictionary"}) is not None
    assert validate_schema({"x": "string"}) is None


# --- the execution path ----------------------------------------------------------------------


def test_text_task_succeeds_with_structured_output_and_settles_actual_usage(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}one")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(_ok_text(json.dumps({"summary": "Warm lead", "score": 0.8}), prompt=12, completion=9))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user, schema={"summary": "string", "score": "number"}),
                                 sleep=_no_sleep)
        db.commit()

    assert result.outcome == "succeeded"
    assert result.reason_code == "ok"
    assert result.structured == {"summary": "Warm lead", "score": 0.8}
    assert result.usage == {"tokens_input": 12, "tokens_output": 9}
    assert result.attempts == 1
    assert provider.calls == 1
    # Settled to actual usage: the output reservation (50) is replaced by the 9 tokens the provider reported.
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 9
    assert _consumed(organization_id, UsageUnit.TOKENS_INPUT) == 12


def test_no_route_is_refused_before_any_reservation_or_call(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}two")
    _configure_budgets(organization_id)
    provider = _Provider()
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "denied"
    assert result.reason_code == "no_route_configured"
    assert provider.calls == 0
    assert _usage_rows(organization_id) == []


def test_a_disabled_capability_is_denied_at_the_gate_without_a_call(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}three")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=organization_id, actor_user_id=user.id,
                               capability_key=CAPABILITY, is_enabled=False)
        db.commit()
    provider = _Provider()
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "denied"
    assert provider.calls == 0


def test_an_exhausted_budget_is_denied_before_the_call(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}four")
    _configure_budgets(organization_id, output=10)  # the request reserves 50 output tokens
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider()
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user, max_tokens=50), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "denied"
    assert result.reason_code == "budget_exhausted"
    assert provider.calls == 0
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 0


def test_a_transient_failure_is_retried_once_and_then_succeeds(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}five")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(httpx.Response(429), _ok_text("Done", prompt=6, completion=3))
    _use_provider(monkeypatch, provider)
    sleeps: list[float] = []

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=sleeps.append)
        db.commit()

    assert result.outcome == "succeeded"
    assert result.attempts == 2
    assert provider.calls == 2
    assert len(sleeps) == 1


def test_a_transient_failure_on_every_attempt_fails_and_releases_the_reservation(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}six")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(httpx.Response(500), httpx.Response(500), httpx.Response(500))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "failed"
    assert result.reason_code == "provider_unavailable"
    assert result.attempts == get_settings().ai_gateway_max_attempts == 2
    assert provider.calls == 2
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 0  # no usage was reported, so nothing is charged


def test_a_timeout_is_reported_as_a_provider_timeout(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}seven")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "failed"
    assert result.reason_code == "provider_timeout"
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 0


def test_a_rejected_credential_is_not_retried(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}eight")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(httpx.Response(401))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.reason_code == "provider_rejected_credential"
    assert result.attempts == 1
    assert provider.calls == 1


def test_invalid_structured_output_fails_but_the_provider_usage_is_still_charged(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}nine")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(_ok_text("This is prose, not JSON.", prompt=8, completion=14))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user, schema={"summary": "string"}),
                                 sleep=_no_sleep)
        db.commit()

    assert result.outcome == "failed"
    assert result.reason_code == "invalid_structured_output"
    assert result.structured is None and result.text is None
    # The provider billed the tokens, so they are settled even though the output is refused.
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 14


def test_a_settlement_failure_withholds_the_answer(enabled, live_settings, monkeypatch):
    """The provider answered, but its usage cannot be recorded. Nothing is returned that was not metered."""
    from app.governance.usage_ledger import ReservationExpiredError

    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}settle")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(_ok_text("Answer the provider produced", prompt=5, completion=5))
    _use_provider(monkeypatch, provider)

    def expired(db, ticket, actual, **_settlement_fields):
        raise ReservationExpiredError("expired")

    monkeypatch.setattr(gateway, "settle_ticket", expired)
    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.rollback()

    assert result.outcome == "failed"
    assert result.reason_code == "usage_settlement_failed"
    assert result.text is None
    assert provider.calls == 1


def test_missing_credential_fails_closed_without_a_call(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider()
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "failed"
    assert result.reason_code == "credential_unavailable"
    assert provider.calls == 0
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 0


def test_live_access_disabled_is_reported_and_releases_the_reservation(enabled, monkeypatch, keyring):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}ten")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    monkeypatch.setenv("PROVIDER_LIVE_ADAPTERS_ENABLED", "false")
    get_settings.cache_clear()
    provider = _Provider()
    _use_provider(monkeypatch, provider, live=False)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()
    get_settings.cache_clear()

    assert result.outcome == "failed"
    assert result.reason_code == "live_adapter_disabled"
    assert provider.calls == 0
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 0


def test_embedding_task_returns_vectors_and_settles_input_tokens(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}eleven")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.EMBEDDING, model="embed-model")
    provider = _Provider(_ok_embedding([[0.1, 0.2], [0.3, 0.4]], prompt=7))
    _use_provider(monkeypatch, provider)

    request = GatewayRequest(
        organization_id=organization_id,
        capability_key=CAPABILITY,
        task=TaskType.EMBEDDING,
        user_context=CurrentUserContext(user=user),
        texts=("first note", "second note"),
        input_token_estimate=20,
    )
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)
        db.commit()

    assert result.outcome == "succeeded"
    assert result.vectors == ((0.1, 0.2), (0.3, 0.4))
    assert result.usage == {"tokens_input": 7}
    assert _consumed(organization_id, UsageUnit.TOKENS_INPUT) == 7


@pytest.mark.parametrize(
    "task, kwargs",
    [
        (TaskType.TEXT, {"text": "   "}),
        (TaskType.TEXT, {"text": "ok", "max_output_tokens": 0}),
        (TaskType.TEXT, {"text": "ok", "max_output_tokens": 10_000}),
        (TaskType.EMBEDDING, {"texts": ()}),
        (TaskType.EMBEDDING, {"texts": ("x",), "input_token_estimate": 0}),
    ],
)
def test_malformed_requests_are_refused_before_anything_is_reserved(enabled, live_settings, monkeypatch, task, kwargs):
    organization_id, user = enabled
    _configure_budgets(organization_id)
    provider = _Provider()
    _use_provider(monkeypatch, provider)
    request = GatewayRequest(organization_id=organization_id, capability_key=CAPABILITY, task=task,
                             user_context=CurrentUserContext(user=user), **kwargs)
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)

    assert result.outcome == "denied"
    assert result.reason_code == "invalid_request"
    assert provider.calls == 0


def test_speech_is_refused_because_no_adapter_serves_it(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _set_route(organization_id, user.id, TaskType.SPEECH)
    provider = _Provider()
    _use_provider(monkeypatch, provider)
    request = GatewayRequest(organization_id=organization_id, capability_key=CAPABILITY, task=TaskType.SPEECH,
                             user_context=CurrentUserContext(user=user))
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)

    assert result.outcome == "denied"
    assert result.reason_code == "task_not_supported"
    assert provider.calls == 0


def test_non_ai_capabilities_are_refused_by_the_gateway(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    request = GatewayRequest(organization_id=organization_id, capability_key="automation.deal_created_rules",
                             task=TaskType.TEXT, user_context=CurrentUserContext(user=user), text="x")
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)
    assert result.outcome == "denied"
    assert result.reason_code == "invalid_request"


def test_the_api_key_never_appears_in_results_or_audit_metadata(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    secret = f"{SECRET_PREFIX}never-leak-me"
    _store_credential(organization_id, user.id, secret)
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(httpx.Response(401))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert secret not in repr(result)
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id)).all()
        assert all(secret not in (row.event_metadata or "") for row in rows)


def test_one_organizations_route_and_credential_are_never_used_for_another(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}org-a")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)

    other_user, other_org = create_owner_manager(permissions=("governance.capabilities.manage",))
    try:
        allow_organization_entitlements(monkeypatch)
        with SessionLocal() as db:
            for key in (AI_MASTER, CAPABILITY):
                set_capability_enabled(db, organization_id=other_org.id, actor_user_id=other_user.id,
                                       capability_key=key, is_enabled=True)
            db.commit()
        _configure_budgets(other_org.id)
        provider = _Provider(_ok_text("never sent"))
        _use_provider(monkeypatch, provider)

        # Organization B has no route, so A's route is not used.
        with SessionLocal() as db:
            result = gateway.execute(db, _text_request(other_org.id, other_user), sleep=_no_sleep)
            db.commit()
        assert result.reason_code == "no_route_configured"

        # Organization B sets its own route but has no credential, so A's credential is not used.
        _set_route(other_org.id, other_user.id, TaskType.TEXT)
        with SessionLocal() as db:
            result = gateway.execute(db, _text_request(other_org.id, other_user), sleep=_no_sleep)
            db.commit()
        assert result.outcome == "failed"
        assert result.reason_code == "credential_unavailable"
        assert provider.calls == 0
    finally:
        _cleanup(other_org.id)


def test_a_route_to_a_non_ai_provider_or_a_bad_model_is_refused(enabled):
    organization_id, user = enabled
    with SessionLocal() as db:
        with pytest.raises(InvalidRouteError):
            set_route(db, organization_id=organization_id, actor_user_id=user.id, task=TaskType.TEXT,
                      provider_key="unknown-provider", model="m")
        with pytest.raises(InvalidRouteError):
            set_route(db, organization_id=organization_id, actor_user_id=user.id, task=TaskType.TEXT,
                      provider_key="openai", model="bad model; drop table")
        db.rollback()


def test_a_route_change_is_audited_with_the_previous_value(enabled):
    organization_id, user = enabled
    _set_route(organization_id, user.id, TaskType.TEXT, model="first-model")
    _set_route(organization_id, user.id, TaskType.TEXT, model="second-model")
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == organization_id, AuditEvent.event_type == "ai_gateway")).all()
    metadata = [json.loads(row.event_metadata) for row in rows]
    assert len(metadata) == 2
    changed = [item for item in metadata if "previous" in item]
    assert len(changed) == 1
    assert changed[0]["model"] == "second-model"
    assert changed[0]["previous"]["provider_key"] == "openai"
    assert changed[0]["previous"]["model"] == "first-model"


def _production_org(monkeypatch, org):
    organization_id, user = org
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    with SessionLocal() as db:
        for key in (AI_MASTER, CAPABILITY):
            set_capability_enabled(db, organization_id=organization_id, actor_user_id=user.id,
                                   capability_key=key, is_enabled=True)
        db.commit()
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    return organization_id, user


def _denied_reason(organization_id, user, provider, resource_id: str | None = None) -> str:
    request = _text_request(organization_id, user)
    request = GatewayRequest(**{**request.__dict__, "resource_id": resource_id})
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)
        db.commit()
    assert result.outcome == "denied"
    assert provider.calls == 0
    return result.reason_code


def test_production_layers_deny_in_order_and_never_reach_the_provider(org, monkeypatch, live_settings):
    """Each layer is still closed in production. The first layer that is not yet approved names the denial."""
    organization_id, user = _production_org(monkeypatch, org)
    provider = _Provider()
    _use_provider(monkeypatch, provider)

    # Layer 1, actor: the AI actor key is pending approval, so no role holds it.
    assert _denied_reason(organization_id, user, provider) == "permission_denied"

    # Layer 2, resource: a named resource is still refused, because no AI resource store exists to prove it published.
    allow_actor_execution_permission(monkeypatch, "governance.consent.read")
    assert _denied_reason(organization_id, user, provider) == "resource_required"
    assert _denied_reason(organization_id, user, provider, resource_id="record-1") == "resource_not_found"

    # Layer 3, rate: with the resource layer passed for a test, no approved rate rule denies the request.
    monkeypatch.setattr(execution_gate, "_gate_resource",
                        lambda db, request, outcomes: (outcomes.append(
                            GateOutcome(gate="resource", allowed=True, reason_code="allowed_all")), None)[1])
    assert _denied_reason(organization_id, user, provider, resource_id="record-1") == "rate_limit_not_configured"


# --- route management over HTTP ----------------------------------------------------------------


def _client_for(tenant: TenantContext | None) -> TestClient:
    app = FastAPI()
    app.include_router(ai_gateway_router)

    def override_session() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_session
    if tenant is not None:
        app.dependency_overrides[get_tenant_context] = lambda: tenant
    return TestClient(app)


def _tenant(user, organization) -> TenantContext:
    from app.db.models.membership import Membership

    with SessionLocal() as db:
        membership = db.scalar(select(Membership).where(
            Membership.user_id == user.id, Membership.organization_id == organization.id))
        assert membership is not None
        db.expunge(membership)
    return TenantContext(organization=organization, membership=membership)


def test_only_the_owner_can_change_a_route_over_http(org):
    organization_id, owner = org
    organization = _org_row(organization_id)
    client = _client_for(_tenant(owner, organization))
    response = client.put("/api/v1/ai/gateway/routes/text", json={"provider_key": "openai", "model": "gpt-test"})
    assert response.status_code == 200
    assert response.json()["model"] == "gpt-test"
    assert "sk-" not in response.text


def test_a_member_cannot_change_a_route_over_http(keyring):
    member, organization = create_manager(permissions=("deals.read",))
    try:
        client = _client_for(_tenant(member, organization))
        response = client.put("/api/v1/ai/gateway/routes/text", json={"provider_key": "openai", "model": "gpt-test"})
        assert response.status_code == 403
    finally:
        _cleanup(organization.id)


def test_a_route_with_an_unknown_provider_is_rejected_over_http(org):
    organization_id, owner = org
    client = _client_for(_tenant(owner, _org_row(organization_id)))
    response = client.put("/api/v1/ai/gateway/routes/text", json={"provider_key": "nope", "model": "m"})
    assert response.status_code == 422


def test_an_unknown_task_is_rejected_over_http(org):
    organization_id, owner = org
    client = _client_for(_tenant(owner, _org_row(organization_id)))
    response = client.put("/api/v1/ai/gateway/routes/video", json={"provider_key": "openai", "model": "m"})
    assert response.status_code == 422


def _org_row(organization_id: uuid.UUID):
    from app.db.models.organization import Organization

    with SessionLocal() as db:
        row = db.get(Organization, organization_id)
        assert row is not None
        db.expunge(row)
        return row


# --- fallback routing and the outcome audit (DFR1-015 completion) ----------------------------


def test_the_fallback_answers_after_the_primary_fails_transiently(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}fallback-a")
    _configure_budgets(organization_id)
    with SessionLocal() as db:
        set_route(db, organization_id=organization_id, actor_user_id=user.id, task=TaskType.TEXT,
                  provider_key="openai", model="primary-model",
                  fallback_provider_key="openai", fallback_model="fallback-model")
        db.commit()
    provider = _Provider(httpx.Response(503), httpx.Response(503),
                         _ok_text("from the fallback", prompt=4, completion=6))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "succeeded"
    assert result.model == "fallback-model"
    assert result.text == "from the fallback"
    assert provider.calls == 3  # two attempts on the primary, then the fallback's first attempt
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 6


def test_the_fallback_is_not_used_after_a_permanent_failure(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}fallback-b")
    _configure_budgets(organization_id)
    with SessionLocal() as db:
        set_route(db, organization_id=organization_id, actor_user_id=user.id, task=TaskType.TEXT,
                  provider_key="openai", model="primary-model",
                  fallback_provider_key="openai", fallback_model="fallback-model")
        db.commit()
    provider = _Provider(httpx.Response(401), _ok_text("must never be asked"))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()

    assert result.outcome == "failed"
    assert result.reason_code == "provider_rejected_credential"
    assert provider.calls == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fallback_provider_key": "openai"},  # a provider without a model
        {"fallback_model": "m"},  # a model without a provider
        {"fallback_provider_key": "openai", "fallback_model": "primary-model"},  # identical to the primary
        {"fallback_provider_key": "not-a-provider", "fallback_model": "m"},  # unknown provider
    ],
)
def test_an_invalid_fallback_is_refused_when_the_route_is_written(enabled, kwargs):
    organization_id, user = enabled
    with SessionLocal() as db:
        with pytest.raises(InvalidRouteError):
            set_route(db, organization_id=organization_id, actor_user_id=user.id, task=TaskType.TEXT,
                      provider_key="openai", model="primary-model", **kwargs)
        db.rollback()


def test_the_outcome_audit_links_requested_and_completed_and_holds_no_content(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    secret = f"{SECRET_PREFIX}audit-never-in-log"
    prompt = "Summarise this private prompt text"
    answer = "A private answer produced by the model"
    _store_credential(organization_id, user.id, secret)
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(_ok_text(answer, prompt=5, completion=7))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user, prompt=prompt), sleep=_no_sleep)
        db.commit()
    assert result.succeeded

    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == organization_id, AuditEvent.event_type == "ai_gateway",
            AuditEvent.action == "ai_gateway.execute")).all()
        for row in rows:
            db.expunge(row)
    requested = [row for row in rows if row.outcome == "requested"]
    completed = [row for row in rows if row.outcome == "completed"]
    assert len(requested) == 1 and len(completed) == 1
    assert completed[0].causation_id == str(requested[0].id)
    payload = json.loads(completed[0].event_metadata)
    assert payload["outcome"] == "succeeded"
    assert payload["usage"] == {"tokens_input": 5, "tokens_output": 7}
    for row in rows:
        assert prompt not in (row.event_metadata or "")
        assert answer not in (row.event_metadata or "")
        assert secret not in (row.event_metadata or "")


def test_a_failed_call_is_still_completed_in_the_audit(enabled, live_settings, monkeypatch):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}audit-fail")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(httpx.Response(401))
    _use_provider(monkeypatch, provider)

    with SessionLocal() as db:
        result = gateway.execute(db, _text_request(organization_id, user), sleep=_no_sleep)
        db.commit()
    assert result.outcome == "failed"

    with SessionLocal() as db:
        completed = db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == organization_id, AuditEvent.action == "ai_gateway.execute",
            AuditEvent.outcome == "completed")).all()
    assert len(completed) == 1
    assert json.loads(completed[0].event_metadata)["reason_code"] == "provider_rejected_credential"


def test_the_route_api_accepts_and_returns_a_fallback(org):
    organization_id, owner = org
    client = _client_for(_tenant(owner, _org_row(organization_id)))
    response = client.put("/api/v1/ai/gateway/routes/text", json={
        "provider_key": "openai", "model": "gpt-primary",
        "fallback_provider_key": "openai", "fallback_model": "gpt-fallback",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_model"] == "gpt-fallback"
    listed = client.get("/api/v1/ai/gateway/routes")
    assert listed.status_code == 403 or listed.json()["items"][0]["fallback_model"] == "gpt-fallback"


def test_the_route_api_refuses_a_half_fallback(org):
    organization_id, owner = org
    client = _client_for(_tenant(owner, _org_row(organization_id)))
    response = client.put("/api/v1/ai/gateway/routes/text", json={
        "provider_key": "openai", "model": "gpt-primary", "fallback_provider_key": "openai",
    })
    assert response.status_code == 422
