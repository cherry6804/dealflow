"""Provider cost, customer credits, pricing versions, workflow and page attribution (DFR1-017).

Provider calls are mocked through the scripted boundary in ``test_ai_gateway``. Nothing here is evidence of live provider usage or of
any real provider price. Prices in these tests are fixture values chosen to make arithmetic checkable.
"""

# ruff: noqa: F401, F811, RUF059  (pytest fixtures imported from other test modules are requested by name)

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select

from app.ai_gateway import service as gateway
from app.ai_gateway.contracts import GatewayRequest
from app.ai_gateway.service import REASON_USAGE_ALREADY_RECORDED
from app.ai_gateway.tasks import TaskType
from app.auth.dependencies import CurrentUserContext
from app.db.models.ai_pricing import AiProviderCostEntry, AiProviderPrice
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.session import SessionLocal
from app.governance.ai_pricing import (
    PricingError,
    create_price_version,
    price_for,
    provider_cost_totals,
    record_provider_costs,
)
from app.governance.usage_ledger import (
    UsageAttribution,
    UsageUnit,
    configure_budget,
    record,
)
from tests.agents_support import world
from tests.test_agents_runtime import agent
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
from tests.test_team_api import create_owner_manager

PRICE_MODEL = "pricing-test-model"


@pytest.fixture(autouse=True)
def _keep_loaded_attributes():
    """The tests read rows after their session commits. Keep loaded attributes readable, and restore the factory afterwards."""
    previous = SessionLocal.kw.get("expire_on_commit", True)
    SessionLocal.configure(expire_on_commit=False)
    yield
    SessionLocal.configure(expire_on_commit=previous)


@pytest.fixture
def prices():
    """Remove the price versions a test created, so no fixture price leaks into another test."""
    created: list[str] = []
    yield created
    with SessionLocal() as db:
        for model in created:
            # Cost entries reference their price version (RESTRICT), so the test's own cost entries go first.
            price_ids = select(AiProviderPrice.id).where(AiProviderPrice.model == model)
            db.execute(
                delete(AiProviderCostEntry).where(
                    AiProviderCostEntry.price_id.in_(price_ids)
                )
            )
            db.execute(delete(AiProviderPrice).where(AiProviderPrice.model == model))
        db.commit()


@pytest.fixture
def costs():
    """Remove the cost entries and usage rows of the organizations a test created."""
    organizations: list[uuid.UUID] = []
    yield organizations
    with SessionLocal() as db:
        for organization_id in organizations:
            db.execute(
                delete(AiProviderCostEntry).where(
                    AiProviderCostEntry.organization_id == organization_id
                )
            )
            db.execute(
                delete(AiUsageEvent).where(
                    AiUsageEvent.organization_id == organization_id
                )
            )
        db.commit()


def _model(prefix: str = "pricing") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _version(
    db,
    *,
    model: str,
    unit: str,
    currency: str,
    price: int,
    per: int,
    at: datetime,
    provider: str = "openai",
) -> AiProviderPrice:
    return create_price_version(
        db,
        provider_key=provider,
        model=model,
        unit=unit,
        currency=currency,
        unit_price_minor=price,
        quantity_per_price=per,
        effective_from=at,
        source_reference="pytest fixture price (not a real rate)",
    )


def _record_usage(
    db,
    organization_id,
    *,
    unit: UsageUnit,
    quantity: int,
    at: datetime,
    model: str,
    provider: str = "openai",
) -> AiUsageEvent:
    return record(
        db,
        organization_id=organization_id,
        unit=unit,
        quantity=quantity,
        idempotency_key=f"usage-{uuid.uuid4().hex}",
        occurred_at=at,
        provider=provider,
        model=model,
        task_type="text",
    )


def _budget(
    db, organization_id, unit: UsageUnit, at: datetime, limit: int = 10_000_000
) -> None:
    configure_budget(
        db, organization_id=organization_id, unit=unit, limit_quantity=limit, moment=at
    )


# --- provider cost and pricing versions ----------------------------------------------------------------


def test_usage_without_a_price_version_is_recorded_as_unpriced_never_as_zero(
    org, costs
):
    organization_id, _user = org
    costs.append(organization_id)
    now = datetime.now(UTC)
    model = _model()
    with SessionLocal() as db:
        _budget(db, organization_id, UsageUnit.TOKENS_OUTPUT, now)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.TOKENS_OUTPUT,
            quantity=7,
            at=now,
            model=model,
        )
        entries = record_provider_costs(
            db,
            organization_id=organization_id,
            events={"tokens_output": event},
            provider_key="openai",
            model=model,
        )
        db.commit()
    assert len(entries) == 1
    assert entries[0].status == AiProviderCostEntry.STATUS_UNPRICED
    assert entries[0].amount_minor is None and entries[0].currency is None
    assert entries[0].reason_code == "no_price_version"
    with SessionLocal() as db:
        totals = provider_cost_totals(
            db,
            organization_id=organization_id,
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        )
    assert totals["priced_minor_by_currency"] == {}
    assert totals["unpriced_entries_by_unit"] == {"tokens_output": 1}


def test_a_priced_entry_keeps_the_version_it_was_calculated_with_after_a_price_change(
    org, costs, prices
):
    organization_id, _user = org
    costs.append(organization_id)
    model = _model()
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=2)
    usage_at = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        _version(
            db,
            model=model,
            unit="tokens_output",
            currency="USD",
            price=3,
            per=1000,
            at=t0,
        )
        _budget(db, organization_id, UsageUnit.TOKENS_OUTPUT, t0)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.TOKENS_OUTPUT,
            quantity=2500,
            at=usage_at,
            model=model,
        )
        first = record_provider_costs(
            db,
            organization_id=organization_id,
            events={"tokens_output": event},
            provider_key="openai",
            model=model,
        )[0]
        db.commit()
    assert first.status == AiProviderCostEntry.STATUS_PRICED
    assert first.price_version == 1
    # ceil(2500 * 3 / 1000) = 8 minor units
    assert first.amount_minor == 8
    assert first.currency == "USD"

    with SessionLocal() as db:
        _version(
            db,
            model=model,
            unit="tokens_output",
            currency="USD",
            price=50,
            per=1000,
            at=datetime.now(UTC) - timedelta(hours=1),
        )
        db.commit()
    with SessionLocal() as db:
        unchanged = db.get(AiProviderCostEntry, first.id)
        assert unchanged.price_version == 1 and unchanged.amount_minor == 8
        current = price_for(
            db,
            provider_key="openai",
            model=model,
            unit="tokens_output",
            at=datetime.now(UTC),
        )
        assert current.version == 2


def test_a_partial_unit_is_rounded_up_so_it_is_never_free(org, costs, prices):
    organization_id, _user = org
    costs.append(organization_id)
    model = _model()
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        _version(
            db,
            model=model,
            unit="tokens_input",
            currency="USD",
            price=1,
            per=1000,
            at=t0,
        )
        _budget(db, organization_id, UsageUnit.TOKENS_INPUT, t0)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.TOKENS_INPUT,
            quantity=1,
            at=datetime.now(UTC),
            model=model,
        )
        entry = record_provider_costs(
            db,
            organization_id=organization_id,
            events={"tokens_input": event},
            provider_key="openai",
            model=model,
        )[0]
        db.commit()
    assert entry.amount_minor == 1


def test_recording_the_same_settlement_twice_creates_one_cost_entry(org, costs, prices):
    organization_id, _user = org
    costs.append(organization_id)
    model = _model()
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        _version(db, model=model, unit="images", currency="USD", price=10, per=1, at=t0)
        _budget(db, organization_id, UsageUnit.IMAGES, t0)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.IMAGES,
            quantity=2,
            at=datetime.now(UTC),
            model=model,
        )
        record_provider_costs(
            db,
            organization_id=organization_id,
            events={"images": event},
            provider_key="openai",
            model=model,
        )
        record_provider_costs(
            db,
            organization_id=organization_id,
            events={"images": event},
            provider_key="openai",
            model=model,
        )
        db.commit()
    with SessionLocal() as db:
        count = len(
            db.scalars(
                select(AiProviderCostEntry.id).where(
                    AiProviderCostEntry.organization_id == organization_id
                )
            ).all()
        )
    assert count == 1


def test_price_versions_must_be_valid_and_must_follow_the_current_version(prices):
    model = _model()
    prices.append(model)
    base = datetime.now(UTC) - timedelta(days=5)
    with SessionLocal() as db:
        _version(
            db,
            model=model,
            unit="tokens_input",
            currency="USD",
            price=2,
            per=1000,
            at=base,
        )
        db.commit()
    cases = [
        (
            "customer_credits",
            "USD",
            2,
            1000,
            base + timedelta(days=1),
            "unpriceable_unit",
        ),
        ("tokens_input", "usd", 2, 1000, base + timedelta(days=1), "invalid_currency"),
        ("tokens_input", "USD", -1, 1000, base + timedelta(days=1), "invalid_price"),
        (
            "tokens_input",
            "USD",
            2,
            0,
            base + timedelta(days=1),
            "invalid_quantity_basis",
        ),
        (
            "tokens_input",
            "USD",
            2,
            1000,
            datetime(2030, 1, 1),
            "effective_from_must_be_aware",
        ),
        (
            "tokens_input",
            "USD",
            2,
            1000,
            base,
            "effective_from_must_follow_current_version",
        ),
    ]
    for unit, currency, price, per, at, reason in cases:
        with SessionLocal() as db:
            with pytest.raises(PricingError) as refused:
                create_price_version(
                    db,
                    provider_key="openai",
                    model=model,
                    unit=unit,
                    currency=currency,
                    unit_price_minor=price,
                    quantity_per_price=per,
                    effective_from=at if at.tzinfo else at.replace(tzinfo=None),
                    source_reference="pytest",
                )
            assert refused.value.reason == reason, (unit, currency, price, per, reason)
            db.rollback()


def test_different_currencies_are_reported_separately_and_never_added(
    org, costs, prices
):
    organization_id, _user = org
    costs.append(organization_id)
    usd_model, inr_model = _model("usd"), _model("inr")
    prices.extend([usd_model, inr_model])
    t0 = datetime.now(UTC) - timedelta(days=1)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        _version(
            db, model=usd_model, unit="images", currency="USD", price=5, per=1, at=t0
        )
        _version(
            db, model=inr_model, unit="images", currency="INR", price=7, per=1, at=t0
        )
        _budget(db, organization_id, UsageUnit.IMAGES, t0)
        usd_event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.IMAGES,
            quantity=3,
            at=now,
            model=usd_model,
        )
        inr_event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.IMAGES,
            quantity=4,
            at=now,
            model=inr_model,
        )
        record_provider_costs(
            db,
            organization_id=organization_id,
            events={"images": usd_event},
            provider_key="openai",
            model=usd_model,
        )
        record_provider_costs(
            db,
            organization_id=organization_id,
            events={"images": inr_event},
            provider_key="openai",
            model=inr_model,
        )
        db.commit()
    with SessionLocal() as db:
        totals = provider_cost_totals(
            db,
            organization_id=organization_id,
            start=now - timedelta(days=2),
            end=now + timedelta(days=1),
        )
    assert totals["priced_minor_by_currency"] == {"USD": 15, "INR": 28}


def test_provider_cost_totals_are_tenant_scoped(org, costs, prices):
    organization_id, _user = org
    costs.append(organization_id)
    _other_user, other_org = create_owner_manager(
        permissions=("governance.capabilities.manage",)
    )
    costs.append(other_org.id)
    model = _model()
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        _version(db, model=model, unit="images", currency="USD", price=5, per=1, at=t0)
        _budget(db, organization_id, UsageUnit.IMAGES, t0)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.IMAGES,
            quantity=2,
            at=datetime.now(UTC),
            model=model,
        )
        record_provider_costs(
            db,
            organization_id=organization_id,
            events={"images": event},
            provider_key="openai",
            model=model,
        )
        db.commit()
    with SessionLocal() as db:
        mine = provider_cost_totals(
            db,
            organization_id=organization_id,
            start=t0 - timedelta(days=1),
            end=datetime.now(UTC) + timedelta(days=1),
        )
        theirs = provider_cost_totals(
            db,
            organization_id=other_org.id,
            start=t0 - timedelta(days=1),
            end=datetime.now(UTC) + timedelta(days=1),
        )
    assert mine["priced_minor_by_currency"] == {"USD": 10}
    assert theirs["priced_minor_by_currency"] == {}


def test_provider_cost_never_creates_or_consumes_customer_credits(org, costs, prices):
    organization_id, _user = org
    costs.append(organization_id)
    model = _model()
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        _version(
            db,
            model=model,
            unit="tokens_output",
            currency="USD",
            price=3,
            per=1000,
            at=t0,
        )
        _budget(db, organization_id, UsageUnit.TOKENS_OUTPUT, t0)
        _budget(db, organization_id, UsageUnit.CUSTOMER_CREDITS, t0)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.TOKENS_OUTPUT,
            quantity=1000,
            at=datetime.now(UTC),
            model=model,
        )
        record_provider_costs(
            db,
            organization_id=organization_id,
            events={"tokens_output": event},
            provider_key="openai",
            model=model,
        )
        db.commit()
    assert _consumed(organization_id, UsageUnit.CUSTOMER_CREDITS) == 0
    with SessionLocal() as db:
        credit_rows = db.scalars(
            select(AiUsageEvent).where(
                AiUsageEvent.organization_id == organization_id,
                AiUsageEvent.unit == UsageUnit.CUSTOMER_CREDITS.value,
            )
        ).all()
    assert credit_rows == []


# --- gateway attribution, fallback, retries and dimensions -----------------------------------------------


def _priced_gateway_model(
    organization_id, prices, costs, *, model: str = "test-model"
) -> None:
    costs.append(organization_id)
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        _version(
            db,
            model=model,
            unit="tokens_input",
            currency="USD",
            price=2,
            per=1000,
            at=t0,
        )
        _version(
            db,
            model=model,
            unit="tokens_output",
            currency="USD",
            price=3,
            per=1000,
            at=t0,
        )
        db.commit()


def test_a_gateway_call_records_priced_provider_cost_and_no_customer_credit(
    enabled, live_settings, monkeypatch, prices, costs
):
    organization_id, user = enabled
    _priced_gateway_model(organization_id, prices, costs)
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}cost")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT, model="test-model")
    _use_provider(
        monkeypatch, _Provider(_ok_text("Priced.", prompt=2000, completion=1000))
    )

    request = GatewayRequest(
        organization_id=organization_id,
        capability_key=CAPABILITY,
        task=TaskType.TEXT,
        user_context=CurrentUserContext(user=user),
        text="Price this.",
        max_output_tokens=50,
        input_token_estimate=30,
    )
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)
        db.commit()
    assert result.outcome == "succeeded"
    with SessionLocal() as db:
        entries = db.scalars(
            select(AiProviderCostEntry).where(
                AiProviderCostEntry.organization_id == organization_id
            )
        ).all()
    by_unit = {entry.unit: entry for entry in entries}
    assert set(by_unit) == {"tokens_input", "tokens_output"}
    assert by_unit["tokens_input"].amount_minor == 4  # 2000 tokens at 2 per 1000
    assert by_unit["tokens_output"].amount_minor == 3  # 1000 tokens at 3 per 1000
    assert all(
        entry.provider_key == "openai" and entry.model == "test-model"
        for entry in entries
    )
    assert all(entry.unit != UsageUnit.CUSTOMER_CREDITS.value for entry in entries)


def test_a_fallback_answer_is_recorded_under_the_provider_and_model_that_answered(
    enabled, live_settings, monkeypatch, prices, costs
):
    organization_id, user = enabled
    model = "fallback-model"
    _priced_gateway_model(organization_id, prices, costs, model=model)
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}fallback-attr")
    _configure_budgets(organization_id)
    with SessionLocal() as db:
        from app.ai_gateway.routing import set_route

        set_route(
            db,
            organization_id=organization_id,
            actor_user_id=user.id,
            task=TaskType.TEXT,
            provider_key="openai",
            model="primary-model",
            fallback_provider_key="openai",
            fallback_model=model,
        )
        db.commit()
    _use_provider(
        monkeypatch,
        _Provider(
            httpx.Response(503),
            httpx.Response(503),
            _ok_text("from fallback", prompt=1000, completion=1000),
        ),
    )
    request = GatewayRequest(
        organization_id=organization_id,
        capability_key=CAPABILITY,
        task=TaskType.TEXT,
        user_context=CurrentUserContext(user=user),
        text="Fallback.",
        max_output_tokens=50,
        input_token_estimate=30,
    )
    with SessionLocal() as db:
        result = gateway.execute(db, request, sleep=_no_sleep)
        db.commit()
    assert result.model == model
    rows = _usage_rows(organization_id)
    output = next(row for row in rows if row.unit == UsageUnit.TOKENS_OUTPUT.value)
    assert output.model == model and output.provider == "openai"
    with SessionLocal() as db:
        entry = db.scalar(
            select(AiProviderCostEntry).where(
                AiProviderCostEntry.organization_id == organization_id,
                AiProviderCostEntry.unit == UsageUnit.TOKENS_OUTPUT.value,
            )
        )
    assert entry.model == model


def test_a_repeated_agent_or_workflow_call_is_metered_once_and_the_provider_is_not_called_again(
    enabled, live_settings, monkeypatch
):
    organization_id, user = enabled
    _store_credential(organization_id, user.id, f"{SECRET_PREFIX}repeat")
    _configure_budgets(organization_id)
    _set_route(organization_id, user.id, TaskType.TEXT)
    provider = _Provider(_ok_text("Once.", prompt=5, completion=9))
    _use_provider(monkeypatch, provider)
    call_key = f"agent:{uuid.uuid4()}:0:0"
    request = GatewayRequest(
        organization_id=organization_id,
        capability_key=CAPABILITY,
        task=TaskType.TEXT,
        user_context=CurrentUserContext(user=user),
        text="Repeat.",
        max_output_tokens=50,
        input_token_estimate=30,
        attribution=UsageAttribution(call_key=call_key),
    )
    with SessionLocal() as db:
        first = gateway.execute(db, request, sleep=_no_sleep)
        db.commit()
    with SessionLocal() as db:
        second = gateway.execute(db, request, sleep=_no_sleep)
        db.commit()
    assert first.outcome == "succeeded"
    assert (
        second.outcome == "denied"
        and second.reason_code == REASON_USAGE_ALREADY_RECORDED
    )
    assert provider.calls == 1
    assert _consumed(organization_id, UsageUnit.TOKENS_OUTPUT) == 9


def test_pages_and_images_are_separate_budget_units_and_separate_settlements():
    request = GatewayRequest(
        organization_id=uuid.uuid4(),
        capability_key=CAPABILITY,
        task=TaskType.MULTIMODAL,
        user_context=CurrentUserContext(user=SimpleNamespace(id=uuid.uuid4())),
        text="Read the pages.",
        max_output_tokens=10,
        input_token_estimate=0,
        images=(object(),),
        document_pages=3,
    )
    units = dict(gateway._budget_units(request))
    assert units["images"] == 1
    assert units["document_pages"] == 3
    actual = gateway._actual_usage({"images": 1}, request)
    assert actual == {"images": 1, "document_pages": 3}


def test_audio_usage_is_accepted_priced_and_preserved_by_the_ledger(org, costs, prices):
    organization_id, _user = org
    costs.append(organization_id)
    model = _model("speech")
    prices.append(model)
    t0 = datetime.now(UTC) - timedelta(days=1)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        _version(
            db, model=model, unit="audio_ms", currency="USD", price=6, per=60000, at=t0
        )
        _budget(db, organization_id, UsageUnit.AUDIO_MS, t0)
        event = _record_usage(
            db,
            organization_id,
            unit=UsageUnit.AUDIO_MS,
            quantity=4200,
            at=now,
            model=model,
        )
        entry = record_provider_costs(
            db,
            organization_id=organization_id,
            events={"audio_ms": event},
            provider_key="openai",
            model=model,
        )[0]
        db.commit()
    with SessionLocal() as db:
        stored = db.get(AiUsageEvent, event.id)
    assert stored.unit == "audio_ms" and stored.quantity == 4200
    assert entry.unit == "audio_ms" and entry.quantity == 4200
    assert entry.amount_minor == 1  # ceil(4200 * 6 / 60000)


# --- workflow and agent attribution ------------------------------------------------------------------


def test_an_agent_run_started_by_a_workflow_step_is_attributed_to_the_execution_and_the_step(
    world, agent, monkeypatch
):
    from app.agents.runtime import create_execution
    from tests.test_agents_runtime import _agent_id, _drain, _user, execution_row

    workflow_execution_id = uuid.uuid4()
    with SessionLocal() as db:
        execution, created = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=_agent_id(world),
            user_context=CurrentUserContext(user=_user(world.member.id)),
            input_values={"contact": str(world.contact_id)},
            idempotency_key=f"workflow:{workflow_execution_id}:helper",
            workflow_execution_id=workflow_execution_id,
            workflow_step_id="helper",
        )
        db.commit()
        execution_id = execution.id
    _drain(world, execution_id)
    rows = [
        row
        for row in _usage_rows(world.org.id)
        if row.execution_id == str(execution_id)
    ]
    assert rows, "the agent's model call must be metered"
    assert all(row.workflow_id == str(workflow_execution_id) for row in rows)
    assert all(row.workflow_step_id == "helper" for row in rows)
    assert all(row.agent_id == str(_agent_id(world)) for row in rows)
    assert all(row.user_id == world.member.id for row in rows)


def test_a_retried_workflow_step_reuses_its_agent_run_and_is_not_metered_twice(
    world, agent
):
    from app.agents.runtime import create_execution
    from tests.test_agents_runtime import _agent_id, _drain, _user

    workflow_execution_id = uuid.uuid4()
    key = f"workflow:{workflow_execution_id}:helper"
    with SessionLocal() as db:
        first, created_first = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=_agent_id(world),
            user_context=CurrentUserContext(user=_user(world.member.id)),
            input_values={"contact": str(world.contact_id)},
            idempotency_key=key,
            workflow_execution_id=workflow_execution_id,
            workflow_step_id="helper",
        )
        db.commit()
        first_id = first.id
    with SessionLocal() as db:
        again, created_again = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=_agent_id(world),
            user_context=CurrentUserContext(user=_user(world.member.id)),
            input_values={"contact": str(world.contact_id)},
            idempotency_key=key,
            workflow_execution_id=workflow_execution_id,
            workflow_step_id="helper",
        )
        db.commit()
    assert created_first is True and created_again is False
    assert first_id == again.id
    _drain(world, first_id)
    _drain(world, first_id)
    model_rows = [
        row
        for row in _usage_rows(world.org.id)
        if row.execution_id == str(first_id)
        and row.unit == UsageUnit.TOKENS_OUTPUT.value
    ]
    assert len(model_rows) == 1
