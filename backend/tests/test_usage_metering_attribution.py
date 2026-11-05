"""AI usage attribution and metering integrity (DFR1-017).

These tests reuse the gateway fixtures and the scripted provider boundary from ``test_ai_gateway``. Provider calls are mocked. Nothing
here is evidence of live provider usage.
"""

# ruff: noqa: F401, F811  (pytest fixtures imported from test_ai_gateway are requested by name)
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.ai_gateway import service as gateway
from app.ai_gateway.contracts import GatewayRequest
from app.ai_gateway.tasks import TaskType
from app.auth.dependencies import CurrentUserContext
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.session import SessionLocal
from app.governance.usage_ledger import UsageAttribution, UsageUnit
from tests.test_ai_gateway import (
    CAPABILITY,
    SECRET_PREFIX,
    _configure_budgets,
    _consumed,
    _no_sleep,
    _ok_text,
    _Provider,
    _set_route,
    _store_credential,
    _usage_rows,
    _use_provider,
    enabled,
    keyring,
    live_settings,
    org,
)


def _request(
    organization_id, user, *, attribution: UsageAttribution | None = None
) -> GatewayRequest:
    return GatewayRequest(
        organization_id=organization_id,
        capability_key=CAPABILITY,
        task=TaskType.TEXT,
        user_context=CurrentUserContext(user=user),
        text="Summarise the lead.",
        max_output_tokens=50,
        input_token_estimate=30,
        attribution=attribution,
    )


def _row(organization_id, unit: UsageUnit) -> AiUsageEvent:
    with SessionLocal() as db:
        row = db.scalar(
            select(AiUsageEvent).where(
                AiUsageEvent.organization_id == organization_id,
                AiUsageEvent.unit == unit.value,
            )
        )
        db.expunge(row)
        return row


def test_settled_usage_records_who_caused_it_which_task_and_which_provider_and_model(
    enabled, live_settings, monkeypatch
):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}attr")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT, model="test-model")
    _use_provider(
        monkeypatch, _Provider(_ok_text("Warm lead.", prompt=12, completion=9))
    )

    with SessionLocal() as db:
        result = gateway.execute(
            db,
            _request(
                organization_id,
                user,
                attribution=UsageAttribution(
                    agent_id="agent-7", execution_id="exec-42"
                ),
            ),
            sleep=_no_sleep,
        )
        db.commit()

    assert result.outcome == "succeeded"
    output = _row(organization_id, UsageUnit.TOKENS_OUTPUT)
    assert output.status == AiUsageEvent.STATUS_RECORDED
    assert output.quantity == 9
    assert output.user_id == user.id
    assert output.provider == "openai"
    assert output.model == "test-model"
    assert output.task_type == "text"
    assert output.agent_id == "agent-7"
    assert output.execution_id == "exec-42"
    assert output.capability_key == CAPABILITY


def test_a_call_without_an_agent_records_no_agent_or_execution(
    enabled, live_settings, monkeypatch
):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}plain")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    _use_provider(monkeypatch, _Provider(_ok_text("Done.", prompt=5, completion=3)))

    with SessionLocal() as db:
        gateway.execute(db, _request(organization_id, user), sleep=_no_sleep)
        db.commit()

    output = _row(organization_id, UsageUnit.TOKENS_OUTPUT)
    assert output.agent_id is None
    assert output.execution_id is None
    assert output.provider == "openai"


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [{"message": {"content": "No usage object."}}]},
        {
            "choices": [{"message": {"content": "Partial usage."}}],
            "usage": {"prompt_tokens": 4},
        },
    ],
    ids=["missing-usage", "partial-usage"],
)
def test_a_provider_answer_without_complete_usage_is_not_charged(
    enabled, live_settings, monkeypatch, body
):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}meta")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    _use_provider(monkeypatch, _Provider(httpx.Response(200, json=body)))

    with SessionLocal() as db:
        result = gateway.execute(db, _request(organization_id, user), sleep=_no_sleep)
        db.commit()

    # The answer is not treated as a success, and the reservation is released rather than charged at the estimate.
    assert result.outcome != "succeeded"
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 0
    assert _consumed(organization_id, UsageUnit.TOKENS_INPUT) == 0
    assert (
        _row(organization_id, UsageUnit.TOKENS_OUTPUT).status
        == AiUsageEvent.STATUS_RELEASED
    )


def test_a_repeated_settlement_of_the_same_call_is_counted_once(
    enabled, live_settings, monkeypatch
):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}once")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    _use_provider(monkeypatch, _Provider(_ok_text("Once.", prompt=6, completion=4)))

    with SessionLocal() as db:
        gateway.execute(db, _request(organization_id, user), sleep=_no_sleep)
        db.commit()

    rows = _usage_rows(organization_id)
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 4
    assert len([row for row in rows if row.unit == UsageUnit.TOKENS_OUTPUT.value]) == 1
