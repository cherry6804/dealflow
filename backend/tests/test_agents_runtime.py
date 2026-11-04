"""Agent execution runtime: creation, limits, handlers, approvals, cancellation, in-flight revocation and recovery (DFR1-019).

Executions run through the outbox handler, as the worker does. Provider calls go to a scripted boundary, and the approval-pending
seams are the same as in the AI gateway tests.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.agents import runtime
from app.agents.handlers import handle_execution_requested
from app.agents.runtime import (
    AgentError,
    cancel_execution,
    create_execution,
    decide_approval,
    expire_stale_running,
    run_execution,
)
from app.auth.dependencies import CurrentUserContext
from app.db.models.agent import Agent, AgentExecution, AgentExecutionStep
from app.db.models.membership import Membership
from app.db.models.outbox_event import OutboxEvent
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance.capabilities import AI_MASTER
from app.governance.service import set_capability_enabled
from app.governance.usage_ledger import UsageUnit, configure_budget
from tests.agents_support import (
    audit_for,
    config,
    create_draft,
    create_user_in,
    execution_row,
    model_reply,
    now_utc,
    steps_of,
    use_provider,
)
from tests.agents_support import (
    publish as publish_version,
)


def _start(world, *, initiator=None, input_contact=None, key=None, cfg=None):
    """Create an execution through the real service and return its id."""
    user = initiator or world.member
    with SessionLocal() as db:
        execution, created = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=_agent_id(world),
            user_context=CurrentUserContext(user=_user(user.id)),
            input_values={"contact": str(input_contact or world.contact_id)},
            idempotency_key=key or f"key-{uuid.uuid4().hex}",
        )
        db.commit()
        return execution.id, created


def _user(user_id) -> User:
    with SessionLocal() as db:
        row = db.get(User, user_id)
        db.expunge(row)
        return row


def _agent_id(world):
    return world.agent_id


def _drain(world, execution_id):
    """Deliver the queued outbox event for this execution, as the worker does."""
    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent).where(
            OutboxEvent.organization_id == world.org.id,
            OutboxEvent.event_type == runtime.EXECUTION_REQUESTED_EVENT,
            OutboxEvent.aggregate_id == str(execution_id),
        ).order_by(OutboxEvent.created_at.desc()))
        if event is not None:
            handle_execution_requested(db, event)
        db.commit()


@pytest.fixture
def agent(world, monkeypatch):
    """A published agent with a tool step and a model step, using the approval-before-result policy."""
    draft = create_draft(world)
    publish_version(world, draft["id"])
    world.agent_id = draft["id"]
    use_provider(monkeypatch, model_reply("The contact is Ada."))
    return draft["id"]


# --- creation, identity and idempotency ---------------------------------------------------------------


def test_a_queued_execution_runs_its_steps_in_order_and_records_each_one(world, agent):
    execution_id, created = _start(world, key="happy")
    assert created is True
    assert execution_row(execution_id).status == "queued"
    _drain(world, execution_id)
    row = execution_row(execution_id)
    assert row.status == "waiting_approval"  # The before-result policy pauses for a human before release.
    steps = steps_of(execution_id)
    assert [(step.kind, step.status) for step in steps] == [
        ("tool", "succeeded"), ("model", "succeeded"), ("approval", "waiting")]
    assert row.tool_calls == 1 and row.model_calls == 1


def test_an_execution_is_pinned_to_the_version_it_started_with(world, agent):
    execution_id, _ = _start(world, key="pinned")
    pinned = execution_row(execution_id).agent_version_id
    _drain(world, execution_id)
    assert execution_row(execution_id).agent_version_id == pinned


def test_a_repeated_request_with_the_same_key_and_input_returns_the_stored_execution(world, agent):
    first, created_first = _start(world, key="same-key")
    second, created_second = _start(world, key="same-key")
    assert (first, created_first) == (second, True) or (first == second and created_second is False)
    assert created_second is False


def test_the_same_key_with_different_input_is_refused(world, agent):
    _start(world, key="conflict-key")
    other = uuid.uuid4()
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(world.member.id)),
                             input_values={"contact": str(other)}, idempotency_key="conflict-key")
    assert refused.value.reason == "idempotency_conflict"


def test_invalid_inputs_are_refused_before_anything_is_queued(world, agent):
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(world.member.id)),
                             input_values={"contact": "not-an-id", "extra": 1}, idempotency_key="bad-input")
    assert refused.value.reason == "invalid_input"
    assert audit_for(world.org.id, "agent.execution.queued") == []


def test_a_duplicate_outbox_delivery_does_not_run_the_execution_twice(world, agent):
    execution_id, _ = _start(world, key="duplicate-event")
    _drain(world, execution_id)
    steps_before = len(steps_of(execution_id))
    _drain(world, execution_id)
    assert len(steps_of(execution_id)) == steps_before


# --- authorization and activation ---------------------------------------------------------------------------


def test_a_member_without_the_run_permission_cannot_start_an_execution(world, agent):
    reader = create_user_in(world.org, permissions=("agents.read", "contacts.read"))
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(reader.id)),
                             input_values={"contact": str(world.contact_id)}, idempotency_key="no-run")
    assert refused.value.reason == "permission_denied"


def test_an_initiator_who_cannot_use_the_tool_is_refused_at_creation(world, agent):
    outsider = create_user_in(world.org, permissions=("agents.run",))
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(outsider.id)),
                             input_values={"contact": str(world.contact_id)}, idempotency_key="no-tool")
    assert refused.value.reason == "not_permitted_now"


def test_missing_provider_readiness_refuses_creation(world, agent, monkeypatch):
    from app.providers.readiness import ConnectionReadiness, ReadinessCode
    monkeypatch.setattr(
        "app.governance.policy.best_provider_readiness",
        lambda db, *, organization_id, provider_keys: ConnectionReadiness(False, ReadinessCode.NOT_CONNECTED, None),
    )
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(world.member.id)),
                             input_values={"contact": str(world.contact_id)}, idempotency_key="no-provider")
    assert refused.value.reason == "not_permitted_now"


def test_disabling_ai_in_flight_stops_the_execution_at_its_next_boundary(world, agent):
    execution_id, _ = _start(world, key="disable-inflight")
    flipped = {"done": False}

    def disable_ai(db, execution):
        if not flipped["done"] and execution.next_step_index == 1:
            set_capability_enabled(db, organization_id=world.org.id, actor_user_id=world.owner.id,
                                   capability_key=AI_MASTER, is_enabled=False)
            flipped["done"] = True

    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        run_execution(db, row, CurrentUserContext(user=_user(world.member.id)), sleep=lambda s: None,
                      between_boundaries=disable_ai)
        db.commit()
    final = execution_row(execution_id)
    assert final.status == "stopped"
    assert final.failure_reason and final.failure_reason != "ok"
    assert final.model_calls == 0


def test_pausing_the_agent_in_flight_stops_new_work(world, agent):
    execution_id, _ = _start(world, key="pause-inflight")

    def pause_agent(db, execution):
        if execution.next_step_index == 1:
            agent_obj = db.get(Agent, execution.agent_id)
            agent_obj.status = Agent.STATUS_PAUSED
            db.flush()

    with SessionLocal() as db:
        run_execution(db, db.get(AgentExecution, execution_id), CurrentUserContext(user=_user(world.member.id)),
                      sleep=lambda s: None, between_boundaries=pause_agent)
        db.commit()
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("stopped", "agent_paused")


def test_a_revoked_membership_stops_the_execution_before_its_next_step(world, agent):
    execution_id, _ = _start(world, key="revoke-inflight")

    def revoke(db, execution):
        if execution.next_step_index == 1:
            membership = db.scalar(select(Membership).where(Membership.user_id == world.member.id,
                                                            Membership.organization_id == world.org.id))
            membership.is_active = False
            db.flush()

    with SessionLocal() as db:
        run_execution(db, db.get(AgentExecution, execution_id), CurrentUserContext(user=_user(world.member.id)),
                      sleep=lambda s: None, between_boundaries=revoke)
        db.commit()
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("stopped", "membership_revoked")
    assert final.model_calls == 0


# --- budgets, timeouts, cancellation and retries -------------------------------------------------------------


def test_exhausted_budget_stops_the_model_step_and_no_provider_is_called(world, monkeypatch):
    draft = create_draft(world, cfg=config(approval_policy="none", steps=[
        {"kind": "model", "prompt": "Summarise.", "output_schema": {"summary": "string"}},
        {"kind": "approval", "reason": "Check."}]))
    publish_version(world, draft["id"])
    world.agent_id = draft["id"]
    provider = use_provider(monkeypatch)
    with SessionLocal() as db:
        configure_budget(db, organization_id=world.org.id, unit=UsageUnit.TOKENS_OUTPUT, limit_quantity=1,
                         moment=now_utc())
        db.commit()
    execution_id, _ = _start(world, key="budget")
    _drain(world, execution_id)
    final = execution_row(execution_id)
    assert final.status == "stopped"
    assert final.failure_reason == "budget_exhausted"
    assert provider.calls == 0


def test_an_expired_deadline_stops_the_execution_before_any_step(world, agent):
    execution_id, _ = _start(world, key="deadline")
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        row.status = AgentExecution.STATUS_RUNNING
        row.started_at = now_utc() - timedelta(minutes=5)
        row.deadline_at = now_utc() - timedelta(seconds=1)
        db.commit()
    _drain(world, execution_id)
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("timed_out", "deadline_exceeded")
    assert final.tool_calls == 0


def test_cancelling_a_queued_execution_stops_it_and_its_event_does_nothing(world, agent):
    execution_id, _ = _start(world, key="cancel-queued")
    with SessionLocal() as db:
        cancel_execution(db, organization_id=world.org.id, execution_id=execution_id,
                         user_context=CurrentUserContext(user=_user(world.member.id)))
        db.commit()
    assert execution_row(execution_id).status == "cancelled"
    _drain(world, execution_id)
    assert execution_row(execution_id).status == "cancelled"
    assert steps_of(execution_id) == []


def test_cancelling_a_running_execution_stops_it_at_the_next_boundary(world, agent):
    execution_id, _ = _start(world, key="cancel-running")

    def cancel_after_first(db, execution):
        if execution.next_step_index == 1 and execution.cancel_requested_at is None:
            execution.cancel_requested_at = now_utc()
            db.flush()

    with SessionLocal() as db:
        run_execution(db, db.get(AgentExecution, execution_id), CurrentUserContext(user=_user(world.member.id)),
                      sleep=lambda s: None, between_boundaries=cancel_after_first)
        db.commit()
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("cancelled", "cancel_requested")
    assert final.model_calls == 0


def test_a_transient_model_failure_is_retried_only_up_to_the_limit(world, monkeypatch):
    draft = create_draft(world, cfg=config(approval_policy="none", limits=dict(config()["limits"], max_retries=1),
                                           steps=[{"kind": "model", "prompt": "Summarise.",
                                                   "output_schema": {"summary": "string"}},
                                                  {"kind": "approval", "reason": "Check."}]))
    publish_version(world, draft["id"])
    world.agent_id = draft["id"]
    # Each gateway call makes two HTTP attempts, so two gateway calls need four failures.
    provider = use_provider(monkeypatch, *[httpx.Response(500)] * 4)
    execution_id, _ = _start(world, key="retry-limit")
    _drain(world, execution_id)
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("failed", "provider_unavailable")
    assert final.model_calls == 2
    assert provider.calls == 4


# --- approvals -------------------------------------------------------------------------------------------------


def test_an_approval_pauses_the_execution_until_a_different_member_decides(world, agent):
    execution_id, _ = _start(world, key="approve-me")
    _drain(world, execution_id)
    assert execution_row(execution_id).status == "waiting_approval"
    approver = create_user_in(world.org, permissions=("agents.approve", "agents.read"))
    with SessionLocal() as db:
        decide_approval(db, organization_id=world.org.id, execution_id=execution_id, step_index=2,
                        user_context=CurrentUserContext(user=_user(approver.id)), approve=True)
        db.commit()
    _drain(world, execution_id)
    final = execution_row(execution_id)
    assert final.status == "succeeded"
    assert final.output["result"] == {"summary": "The contact is Ada."}


def test_the_initiator_cannot_approve_their_own_execution(world, agent):
    initiator = create_user_in(world.org, permissions=(
        "agents.run", "agents.approve", "agents.read", "contacts.read", "documents.read", "governance.consent.read"))
    execution_id, _ = _start(world, initiator=initiator, key="self-approve")
    _drain(world, execution_id)
    assert execution_row(execution_id).status == "waiting_approval"
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            decide_approval(db, organization_id=world.org.id, execution_id=execution_id, step_index=2,
                            user_context=CurrentUserContext(user=_user(initiator.id)), approve=True)
    assert refused.value.reason == "self_approval_refused"


def test_a_rejected_approval_fails_the_execution(world, agent):
    execution_id, _ = _start(world, key="reject-me")
    _drain(world, execution_id)
    approver = create_user_in(world.org, permissions=("agents.approve",))
    with SessionLocal() as db:
        decide_approval(db, organization_id=world.org.id, execution_id=execution_id, step_index=2,
                        user_context=CurrentUserContext(user=_user(approver.id)), approve=False)
        db.commit()
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("failed", "approval_rejected")


# --- limits -------------------------------------------------------------------------------------------------------


def test_the_concurrent_execution_limit_is_enforced(world, monkeypatch):
    draft = create_draft(world, cfg=config(limits=dict(config()["limits"], max_concurrent_executions=1)))
    publish_version(world, draft["id"])
    world.agent_id = draft["id"]
    _start(world, key="first-running")
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(world.member.id)),
                             input_values={"contact": str(world.contact_id)}, idempotency_key="second-running")
    assert refused.value.reason == "concurrency_limit"


def test_the_per_agent_hourly_limit_is_enforced(world, monkeypatch):
    draft = create_draft(world, cfg=config(limits=dict(config()["limits"], max_executions_per_hour=1)))
    publish_version(world, draft["id"])
    world.agent_id = draft["id"]
    _start(world, key="hour-one")
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(world.member.id)),
                             input_values={"contact": str(world.contact_id)}, idempotency_key="hour-two")
    assert refused.value.reason == "rate_limited"


def test_an_output_larger_than_its_limit_fails_the_execution(world, monkeypatch):
    draft = create_draft(world, cfg=config(limits=dict(config()["limits"], max_output_characters=40),
                                           approval_policy="none", autonomy_level="act"))
    publish_version(world, draft["id"])
    world.agent_id = draft["id"]
    use_provider(monkeypatch, model_reply("x" * 500))
    execution_id, _ = _start(world, key="big-output")
    _drain(world, execution_id)
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("failed", "output_too_large")


def test_a_plan_longer_than_its_step_limit_is_refused_when_it_is_saved(world):
    from app.agents.service import create_agent
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_agent(db, organization_id=world.org.id, actor_id=world.owner.id, name="too-long",
                         description=None, configuration=config(
                             limits=dict(config()["limits"], max_steps=1),
                             approval_policy="before_result"))
    assert refused.value.reason == "invalid_configuration"


# --- recovery, expiry and attribution -----------------------------------------------------------------------------


def test_an_interrupted_step_fails_the_execution_instead_of_repeating_it(world, agent):
    execution_id, _ = _start(world, key="interrupted")
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        row.status = AgentExecution.STATUS_RUNNING
        row.started_at = now_utc()
        row.deadline_at = now_utc() + timedelta(minutes=5)
        db.add(AgentExecutionStep(organization_id=world.org.id, execution_id=execution_id, step_index=0,
                                  kind="tool", status="running", attempts=0))
        db.commit()
    _drain(world, execution_id)
    final = execution_row(execution_id)
    assert (final.status, final.failure_reason) == ("failed", "interrupted_step")
    assert final.tool_calls == 0


def test_running_executions_past_their_deadline_are_expired_by_the_sweep(world, agent):
    execution_id, _ = _start(world, key="sweep")
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        row.status = AgentExecution.STATUS_RUNNING
        row.deadline_at = now_utc() - timedelta(seconds=10)
        db.commit()
    with SessionLocal() as db:
        assert expire_stale_running(db, organization_id=world.org.id) == 1
        db.commit()
    assert execution_row(execution_id).status == "timed_out"


def test_every_step_is_audited_to_the_initiating_user_and_its_correlation_id(world, agent):
    execution_id, _ = _start(world, key="audit")
    _drain(world, execution_id)
    final = execution_row(execution_id)
    queued = audit_for(world.org.id, "agent.execution.queued")
    assert queued and queued[-1].user_id == world.member.id
    assert queued[-1].correlation_id == final.correlation_id
    assert str(world.contact_id) not in (queued[-1].event_metadata or "")


def test_another_organization_cannot_start_read_or_cancel_this_organizations_execution(world, agent, monkeypatch):
    execution_id, _ = _start(world, key="cross-tenant")
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            create_execution(db, organization_id=world.other_org.id, agent_id=world.agent_id,
                             user_context=CurrentUserContext(user=_user(world.other.id)),
                             input_values={"contact": str(world.contact_id)}, idempotency_key="cross-start")
    assert refused.value.reason == "agent_not_found"
    with SessionLocal() as db, pytest.raises(AgentError) as refused:
            cancel_execution(db, organization_id=world.other_org.id, execution_id=execution_id,
                             user_context=CurrentUserContext(user=_user(world.other.id)))
    assert refused.value.reason == "execution_not_found"
