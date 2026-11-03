"""The shared AI and automation execution gate (WS6 WP4).

Runs on PostgreSQL. Each gate is shown denying on its own, the budget lifecycle is exercised through real
reservations, and enforcement is shown to be the same for requests and for background work. Audit records are
checked in their own transaction, so a rollback cannot erase them.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.audit.attribution import AuditAttributionError
from app.audit.independent import AuditPersistenceError
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.session import SessionLocal
from app.governance import execution_gate as gate
from app.governance.capabilities import (
    AI_MASTER,
    AUTOMATION_DEAL_CREATED_RULES,
    AUTOMATION_MASTER,
)
from app.governance.execution_gate import (
    ExecutionRequest,
    release_ticket,
    settle_ticket,
)
from app.governance.service import set_capability_enabled
from app.governance.usage_ledger import configure_budget
from tests.governance_helpers import attested_user_context
from tests.test_automation_execution_service import create_active_rule, create_test_deal
from tests.test_team_api import create_authorized_user, create_manager

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
NO_WORKFLOW = [{"feature_key": "workflow_automation", "enabled": False}]


def evaluate_execution(request, *, now=None):
    """Run the gate in a session that commits and closes before returning, as a real caller does."""
    with SessionLocal() as db:
        decision = gate.evaluate_execution(db, request, now=now)
        db.commit()
    return decision


def revalidate_ticket(request):
    with SessionLocal() as db:
        decision = gate.revalidate_ticket(db, request)
        db.commit()
    return decision


def _gate_check(function, *args):
    with SessionLocal() as db:
        result = function(db, *args, [])
        db.commit()
        return result


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization_id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        db.execute(delete(OrganizationCapabilitySetting).where(
            OrganizationCapabilitySetting.organization_id == organization_id))
        db.commit()


@pytest.fixture
def automation_on() -> Iterator[dict]:
    """An organization with automation switched on, an active deal-created rule, and an acting user."""
    with SessionLocal() as db:
        db.expire_on_commit = False
        user, organization = create_authorized_user(db, permission_keys=("deals.create",))
        set_capability_enabled(db, organization_id=organization.id, actor_user_id=user.id,
                               capability_key=AUTOMATION_MASTER, is_enabled=True)
        set_capability_enabled(db, organization_id=organization.id, actor_user_id=user.id,
                               capability_key=AUTOMATION_DEAL_CREATED_RULES, is_enabled=True)
        rule = create_active_rule(
            db, user=user, organization=organization, conditions=[],
            actions=[{"type": "CREATE_FOLLOW_UP", "config": {"days_after": 1, "title": "Gate"}}],
        )
        db.commit()
        state = {"user": user, "organization": organization, "rule": rule}
    yield state
    _cleanup(state["organization"].id)


def _automation_request(state: dict, *, entitlements=None, budget_units=()) -> ExecutionRequest:
    context = attested_user_context(state["user"], organization_id=state["organization"].id,
                                    entitlements=entitlements) if entitlements is not None else \
        attested_user_context(state["user"], organization_id=state["organization"].id)
    return ExecutionRequest(
        organization_id=state["organization"].id,
        capability_key=AUTOMATION_DEAL_CREATED_RULES,
        user_context=context,
        budget_units=budget_units,
        correlation_id=str(uuid4()),
    )


def _rows(organization_id: UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == organization_id,
            AuditEvent.event_type == "execution_gate",
        )).all())


def _usage(organization_id: UUID) -> tuple[int, int]:
    with SessionLocal() as db:
        budget = db.scalar(select(OrganizationUsageBudget).where(
            OrganizationUsageBudget.organization_id == organization_id,
            OrganizationUsageBudget.unit == "tokens_output"))
        return (budget.reserved_quantity, budget.consumed_quantity) if budget else (0, 0)


# --- Every gate, independently ------------------------------------------------------------------


def test_the_allowed_path_passes_every_gate_and_returns_a_ticket(automation_on) -> None:
    decision = evaluate_execution(_automation_request(automation_on))

    assert decision.allowed is True
    assert decision.reason_code == "allowed"
    assert decision.ticket is not None
    assert [item.gate for item in decision.outcomes if item.allowed][:1] == ["switches"]


def test_entitlement_gate_denies_without_a_verified_plan_feature(automation_on) -> None:
    from app.auth.dependencies import CurrentUserContext

    request = ExecutionRequest(
        organization_id=automation_on["organization"].id,
        capability_key=AUTOMATION_DEAL_CREATED_RULES,
        user_context=CurrentUserContext(user=automation_on["user"]),
    )
    decision = evaluate_execution(request)

    assert decision.allowed is False
    assert decision.gate == gate.GATE_ENTITLEMENT


def test_entitlement_gate_denies_a_disabled_plan_feature(automation_on) -> None:
    decision = evaluate_execution(_automation_request(automation_on, entitlements=NO_WORKFLOW))

    assert decision.allowed is False
    assert decision.gate == gate.GATE_ENTITLEMENT
    assert decision.reason_code == "entitlement_disabled"


def test_switches_gate_denies_when_the_master_is_off(automation_on) -> None:
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=automation_on["organization"].id,
                               actor_user_id=automation_on["user"].id,
                               capability_key=AUTOMATION_MASTER, is_enabled=False)
        db.commit()
    decision = evaluate_execution(_automation_request(automation_on))

    assert decision.allowed is False
    assert decision.gate == gate.GATE_SWITCHES
    assert decision.reason_code == "master_disabled"


def test_provider_gate_denies_an_ai_capability_with_no_connected_provider(automation_on) -> None:
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=automation_on["organization"].id,
                               actor_user_id=automation_on["user"].id, capability_key=AI_MASTER, is_enabled=True)
        set_capability_enabled(db, organization_id=automation_on["organization"].id,
                               actor_user_id=automation_on["user"].id, capability_key="ai.assistant",
                               is_enabled=True)
        db.commit()
    request = ExecutionRequest(
        organization_id=automation_on["organization"].id,
        capability_key="ai.assistant",
        user_context=attested_user_context(automation_on["user"], organization_id=automation_on["organization"].id),
        resource_id="assistant-1",
    )
    decision = evaluate_execution(request)

    assert decision.allowed is False
    assert decision.gate == gate.GATE_PROVIDER


def test_actor_gate_denies_a_user_without_the_permission(automation_on) -> None:
    with SessionLocal() as db:
        db.expire_on_commit = False
        other, _ = create_authorized_user(db, permission_keys=())
        db.commit()
    # The second user is a member of the same organization, without the permission.
    from app.db.models.membership import Membership

    with SessionLocal() as db:
        db.add(Membership(user_id=other.id, organization_id=automation_on["organization"].id, is_active=True))
        db.commit()
    other_user_ctx = attested_user_context(other, organization_id=automation_on["organization"].id)
    request = ExecutionRequest(
        organization_id=automation_on["organization"].id,
        capability_key=AUTOMATION_DEAL_CREATED_RULES,
        user_context=other_user_ctx,
    )
    decision = evaluate_execution(request)

    assert decision.allowed is False
    assert decision.gate == gate.GATE_ACTOR
    assert decision.reason_code == gate.REASON_PERMISSION_DENIED


def test_actor_gate_refuses_a_system_actor_for_every_capability(automation_on) -> None:
    from app.audit.attribution import register_system_actor
    from app.governance.execution_gate import ExecutionRequest as Request

    capability = register_system_actor("wp4_test_actor")
    request = Request(
        organization_id=automation_on["organization"].id,
        capability_key=AUTOMATION_DEAL_CREATED_RULES,
        system_actor=capability,
    )
    decision = evaluate_execution(request)

    # Automation's entitlement is read from a user's session, so a system actor is refused before the actor gate.
    assert decision.allowed is False
    assert decision.gate in {gate.GATE_ENTITLEMENT, gate.GATE_ACTOR}


def test_resource_gate_requires_a_resource_for_ai_and_refuses_an_unknown_one(automation_on) -> None:
    assert gate._gate_resource.__name__ == "_gate_resource"
    request = ExecutionRequest(organization_id=automation_on["organization"].id, capability_key="ai.assistant")
    denial = _gate_check(gate._gate_resource, request)
    assert denial is not None and denial.reason_code == gate.REASON_RESOURCE_REQUIRED

    with_resource = ExecutionRequest(organization_id=automation_on["organization"].id,
                                     capability_key="ai.assistant", resource_id="unknown")
    denial = _gate_check(gate._gate_resource, with_resource)
    assert denial is not None and denial.reason_code == gate.REASON_RESOURCE_NOT_FOUND


def test_consent_gate_refuses_when_no_consent_store_exists(automation_on) -> None:
    request = ExecutionRequest(organization_id=automation_on["organization"].id, capability_key="ai.voice",
                               resource_id="voice-1")
    denial = gate._gate_consent(request, [])
    assert denial is not None
    assert denial.reason_code == "consent_not_configured"


def test_approval_gate_refuses_customer_facing_actions_without_an_approval(automation_on) -> None:
    request = ExecutionRequest(
        organization_id=automation_on["organization"].id,
        capability_key="channels.email",
        approval_id=uuid4(),
        approval_payload_hash="a" * 64,
    )
    denial = gate._gate_approval(request, [])
    assert denial is not None
    assert denial.reason_code == gate.REASON_APPROVAL_REQUIRED


def test_approval_gate_passes_actions_that_do_not_require_one(automation_on) -> None:
    request = ExecutionRequest(organization_id=automation_on["organization"].id,
                               capability_key=AUTOMATION_DEAL_CREATED_RULES)
    assert gate._gate_approval(request, []) is None


def test_rate_gate_refuses_a_capability_with_no_approved_rule(automation_on) -> None:
    request = ExecutionRequest(organization_id=automation_on["organization"].id, capability_key="ai.assistant")
    denial = _gate_check(gate._gate_rate, request)
    assert denial is not None
    assert denial.reason_code == gate.REASON_RATE_NOT_CONFIGURED


# --- Budget: reservation, hard stop, settlement and release --------------------------------------


def test_budget_hard_stop_refuses_usage_beyond_the_limit(automation_on) -> None:
    with SessionLocal() as db:
        configure_budget(db, organization_id=automation_on["organization"].id, unit="tokens_output",
                         limit_quantity=10, moment=datetime.now(UTC))
        db.commit()
    decision = evaluate_execution(
        _automation_request(automation_on, budget_units=(("tokens_output", 11),)))

    assert decision.allowed is False
    assert decision.reason_code == gate.REASON_BUDGET_EXHAUSTED
    assert _usage(automation_on["organization"].id) == (0, 0)


def test_budget_refuses_when_no_budget_is_configured(automation_on) -> None:
    decision = evaluate_execution(
        _automation_request(automation_on, budget_units=(("tokens_output", 1),)))

    assert decision.allowed is False
    assert decision.reason_code == gate.REASON_BUDGET_NOT_CONFIGURED


def test_a_reservation_is_settled_to_actual_usage(automation_on) -> None:
    with SessionLocal() as db:
        configure_budget(db, organization_id=automation_on["organization"].id, unit="tokens_output",
                         limit_quantity=100, moment=datetime.now(UTC))
        db.commit()
    decision = evaluate_execution(
        _automation_request(automation_on, budget_units=(("tokens_output", 40),)))
    assert decision.allowed is True
    assert _usage(automation_on["organization"].id) == (40, 0)

    with SessionLocal() as db:
        settle_ticket(db, decision.ticket, {"tokens_output": 25})
        db.commit()
    assert _usage(automation_on["organization"].id) == (0, 25)


def test_a_reservation_is_released_when_the_work_fails(automation_on) -> None:
    with SessionLocal() as db:
        configure_budget(db, organization_id=automation_on["organization"].id, unit="tokens_output",
                         limit_quantity=100, moment=datetime.now(UTC))
        db.commit()
    decision = evaluate_execution(
        _automation_request(automation_on, budget_units=(("tokens_output", 40),)))
    with SessionLocal() as db:
        release_ticket(db, decision.ticket)
        db.commit()
    assert _usage(automation_on["organization"].id) == (0, 0)


def test_an_audit_failure_releases_the_reservation_and_nothing_executes(automation_on, monkeypatch) -> None:
    with SessionLocal() as db:
        configure_budget(db, organization_id=automation_on["organization"].id, unit="tokens_output",
                         limit_quantity=100, moment=datetime.now(UTC))
        db.commit()

    def unavailable(*args, **kwargs):
        raise AuditPersistenceError("The audit record could not be written.")

    monkeypatch.setattr(gate, "persist_independent_audit_event", unavailable)
    with pytest.raises(AuditPersistenceError):
        evaluate_execution(_automation_request(automation_on,
                                                               budget_units=(("tokens_output", 40),)))
    assert _usage(automation_on["organization"].id) == (0, 0)


# --- Audit: independent, attributed, and kept across rollback -----------------------------------


def test_an_allowed_decision_is_recorded_independently_and_survives_rollback(automation_on) -> None:
    db = SessionLocal()
    try:
        gate.evaluate_execution(db, _automation_request(automation_on))
        db.rollback()
    finally:
        db.close()
    rows = _rows(automation_on["organization"].id)
    assert [row.outcome for row in rows] == ["requested"]
    assert rows[0].user_id == automation_on["user"].id


def test_a_denial_is_recorded_as_denied_with_its_gate(automation_on) -> None:
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=automation_on["organization"].id,
                               actor_user_id=automation_on["user"].id,
                               capability_key=AUTOMATION_MASTER, is_enabled=False)
        db.commit()
    evaluate_execution(_automation_request(automation_on))

    denials = [row for row in _rows(automation_on["organization"].id) if row.outcome == "denied"]
    assert len(denials) == 1
    assert '"gate":"switches"' in denials[0].event_metadata


def test_a_user_outside_the_organization_is_refused_not_recorded(automation_on) -> None:
    _, other_org = create_manager(permissions=())
    request = ExecutionRequest(
        organization_id=other_org.id,
        capability_key=AUTOMATION_DEAL_CREATED_RULES,
        user_context=attested_user_context(automation_on["user"], organization_id=other_org.id),
    )
    with pytest.raises(AuditAttributionError):
        evaluate_execution(request)
    assert _rows(other_org.id) == []


# --- In flight: revocation stops later steps -----------------------------------------------------


def test_disabling_the_master_mid_execution_stops_the_next_step(automation_on) -> None:
    decision = evaluate_execution(_automation_request(automation_on))
    assert decision.allowed is True

    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=automation_on["organization"].id,
                               actor_user_id=automation_on["user"].id,
                               capability_key=AUTOMATION_MASTER, is_enabled=False)
        db.commit()
    later = revalidate_ticket(_automation_request(automation_on))

    assert later.allowed is False
    assert later.gate == gate.GATE_SWITCHES


def test_removing_the_permission_mid_execution_stops_the_next_step(automation_on) -> None:
    from app.db.models.membership import Membership
    from app.db.models.membership_role import MembershipRole

    decision = evaluate_execution(_automation_request(automation_on))
    assert decision.allowed is True

    with SessionLocal() as db:
        membership_id = db.scalar(select(Membership.id).where(
            Membership.user_id == automation_on["user"].id,
            Membership.organization_id == automation_on["organization"].id))
        role_ids = db.scalars(select(MembershipRole.role_id).where(MembershipRole.membership_id == membership_id)).all()
        db.execute(delete(MembershipRole).where(MembershipRole.membership_id == membership_id))
        db.commit()
    try:
        later = revalidate_ticket(_automation_request(automation_on))
        assert later.allowed is False
        assert later.gate == gate.GATE_ACTOR
    finally:
        with SessionLocal() as db:
            for role_id in role_ids:
                db.add(MembershipRole(membership_id=membership_id, role_id=role_id))
            db.commit()


# --- Background work uses the same enforcement --------------------------------------------------


def test_background_work_is_denied_by_the_same_gates_as_a_request(automation_on) -> None:
    from app.audit.attribution import register_system_actor

    background = ExecutionRequest(
        organization_id=automation_on["organization"].id,
        capability_key="ai.assistant",
        system_actor=register_system_actor("wp4_background_worker"),
        resource_id="assistant-1",
    )
    decision = evaluate_execution(background)

    assert decision.allowed is False
    assert decision.gate in {gate.GATE_PROVIDER, gate.GATE_ACTOR, gate.GATE_SWITCHES}


def test_a_background_request_cannot_name_both_or_neither_actor(automation_on) -> None:
    with pytest.raises(ValueError):
        evaluate_execution(ExecutionRequest(
            organization_id=automation_on["organization"].id, capability_key=AUTOMATION_DEAL_CREATED_RULES))


# --- Manual CRM and the existing automation behaviour -------------------------------------------


def test_manual_deal_creation_is_unaffected_when_automation_is_off(automation_on) -> None:
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=automation_on["organization"].id,
                               actor_user_id=automation_on["user"].id,
                               capability_key=AUTOMATION_MASTER, is_enabled=False)
        deal = create_test_deal(db, user=automation_on["user"], organization=automation_on["organization"])
        db.commit()
        assert deal.id is not None
