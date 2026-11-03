"""DFR1-006: the centralized execution gate, negative cases and in-flight revalidation.

Every case runs against PostgreSQL through the real execution service. Each test creates its own
organization, so nothing is shared between tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.automation_rules import execution_service
from app.automation_rules.execution_service import execute_deal_created_automations
from app.db.models.audit_event import AuditEvent
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.db.models.membership import Membership
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance.capabilities import (
    AI_MASTER,
    AUTOMATION_DEAL_CREATED_RULES,
    AUTOMATION_MASTER,
    CAPABILITY_BY_KEY,
)
from app.governance.execution_gate import (
    EXECUTION_AUDIT_ACTION,
    ExecutionRequest,
    authorize_execution,
)
from app.governance.policy import evaluate_capability
from app.governance.service import set_capability_enabled
from tests.governance_helpers import attested_user_context
from tests.test_automation_execution_service import create_test_deal
from tests.test_deals_api import create_authorized_user, create_lead

FOLLOW_UP_ACTION = [
    {"type": "CREATE_FOLLOW_UP", "config": {"title": "Call the new lead", "due_in_days": 1}}
]
MATCHING = [{"field": "stage", "operator": "equals", "value": "NEW"}]


def _scenario(
    *,
    rule_count: int = 1,
    action_count: int = 1,
    rule_status: str = AutomationRule.STATUS_ACTIVE,
    enable: bool = True,
) -> dict[str, UUID]:
    """Create an organization, a user, a deal and rules. Return their identifiers."""
    with SessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(db, user=user, organization=organization, lead_id=lead.id)
        rule_ids: list[UUID] = []
        for index in range(rule_count):
            rule = AutomationRule(
                # Explicit creation times make the run order deterministic (rules are ordered
                # by created_at, then by a random ID that is not stable across runs).
                created_at=datetime.now(UTC) + timedelta(seconds=index),
                organization_id=organization.id,
                name=f"Gate rule {index}",
                description="Execution gate",
                trigger_type="DEAL_CREATED",
                trigger_config={},
                conditions=MATCHING,
                actions=FOLLOW_UP_ACTION * action_count,
                status=rule_status,
                created_by_user_id=user.id,
            )
            db.add(rule)
            db.flush()
            rule_ids.append(rule.id)
        if enable:
            for key in (AUTOMATION_MASTER, AUTOMATION_DEAL_CREATED_RULES):
                set_capability_enabled(
                    db,
                    organization_id=organization.id,
                    actor_user_id=user.id,
                    capability_key=key,
                    is_enabled=True,
                )
        db.commit()
        return {
            "user_id": user.id,
            "organization_id": organization.id,
            "deal_id": deal.id,
            "rule_ids": rule_ids,
        }


def _run(ids: dict[str, UUID], *, context_kwargs: dict | None = None, no_actor: bool = False) -> list:
    """Run deal-created automations and return the executions created."""
    with SessionLocal() as db:
        deal = db.get(Deal, ids["deal_id"])
        user = db.get(User, ids["user_id"])
        assert deal is not None and user is not None
        context = (
            None
            if no_actor
            else attested_user_context(
                user, organization_id=ids["organization_id"], **(context_kwargs or {})
            )
        )
        executions = execute_deal_created_automations(
            db,
            organization_id=ids["organization_id"],
            deal=deal,
            user_context=context,
        )
        db.commit()
        return executions


def _set(ids: dict[str, UUID], key: str, enabled: bool) -> None:
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=ids["organization_id"],
            actor_user_id=ids["user_id"],
            capability_key=key,
            is_enabled=enabled,
        )
        db.commit()


def _gate_audits(organization_id: UUID) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == EXECUTION_AUDIT_ACTION,
            )
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        ).all()
        return [
            {
                "decision": row.decision,
                "resource_type": row.resource_type,
                "metadata": json.loads(row.event_metadata),
            }
            for row in rows
        ]


def _execution_count(organization_id: UUID) -> int:
    with SessionLocal() as db:
        return len(
            db.scalars(
                select(AutomationExecution.id).where(
                    AutomationExecution.organization_id == organization_id
                )
            ).all()
        )


def _denied_reasons(organization_id: UUID) -> list[str]:
    return [
        audit["metadata"]["reason_code"]
        for audit in _gate_audits(organization_id)
        if audit["decision"] == "denied"
    ]


# --- Disabled by default, opt-in and revocation -----------------------------------------------


def test_a_new_organization_never_runs_deal_automation(monkeypatch) -> None:
    ids = _scenario(enable=False)

    executions = _run(ids)

    assert executions == []
    assert _execution_count(ids["organization_id"]) == 0
    assert _denied_reasons(ids["organization_id"]) == ["master_disabled"]


def test_manual_deal_creation_still_works_when_automation_is_off() -> None:
    ids = _scenario(enable=False)

    assert _run(ids) == []
    with SessionLocal() as db:
        deal = db.get(Deal, ids["deal_id"])
        assert deal is not None
        assert deal.organization_id == ids["organization_id"]


def test_revoking_opt_in_stops_the_next_run_and_is_audited() -> None:
    ids = _scenario()
    assert len(_run(ids)) == 1

    _set(ids, AUTOMATION_MASTER, False)
    later = _run(ids)

    assert later == []
    assert _denied_reasons(ids["organization_id"]) == ["master_disabled"]


def test_a_child_switch_turned_off_denies_with_its_own_reason() -> None:
    ids = _scenario()
    _set(ids, AUTOMATION_DEAL_CREATED_RULES, False)

    assert _run(ids) == []
    assert _denied_reasons(ids["organization_id"]) == ["capability_disabled"]


# --- Entitlement, subscription and membership ---------------------------------------------------


def test_an_expired_trial_denies_even_when_switches_are_on() -> None:
    ids = _scenario()

    executions = _run(ids, context_kwargs={"subscription_status": "expired"})

    assert executions == []
    assert _execution_count(ids["organization_id"]) == 0
    assert _denied_reasons(ids["organization_id"]) == ["trial_expired"]


def test_a_plan_without_the_feature_denies() -> None:
    ids = _scenario()

    assert _run(ids, context_kwargs={"entitlements": []}) == []
    assert _denied_reasons(ids["organization_id"]) == ["entitlement_missing"]


def test_a_disabled_plan_feature_denies() -> None:
    ids = _scenario()
    entitlement = [{"feature_key": "workflow_automation", "enabled": False}]

    assert _run(ids, context_kwargs={"entitlements": entitlement}) == []
    assert _denied_reasons(ids["organization_id"]) == ["entitlement_disabled"]


def test_revoked_product_access_denies() -> None:
    ids = _scenario()

    assert _run(ids, context_kwargs={"product_role": None}) == []
    assert _denied_reasons(ids["organization_id"]) == ["product_membership_inactive"]


def test_an_unverified_snapshot_fails_closed() -> None:
    ids = _scenario()

    assert _run(ids, context_kwargs={"sibvo_attested": False}) == []
    assert _denied_reasons(ids["organization_id"]) == ["entitlement_unverified"]


def test_a_session_for_another_organization_is_refused() -> None:
    ids = _scenario()
    other = uuid4()

    assert _run(ids, context_kwargs={"session_organization_id": other}) == []
    assert _denied_reasons(ids["organization_id"]) == ["wrong_organization"]


def test_an_inactive_membership_denies_even_with_a_valid_snapshot() -> None:
    ids = _scenario()
    with SessionLocal() as db:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == ids["user_id"],
                Membership.organization_id == ids["organization_id"],
            )
        )
        assert membership is not None
        membership.is_active = False
        db.commit()

    assert _run(ids) == []
    assert _denied_reasons(ids["organization_id"]) == ["membership_inactive"]


# --- Actor authorization ------------------------------------------------------------------------


def test_an_execution_without_an_actor_is_refused() -> None:
    ids = _scenario()

    assert _run(ids, no_actor=True) == []
    assert _execution_count(ids["organization_id"]) == 0
    audits = _gate_audits(ids["organization_id"])
    assert audits and audits[-1]["metadata"]["reason_code"] == "actor_required"


def test_an_actor_without_the_permission_for_the_action_is_refused() -> None:
    ids = _scenario()
    with SessionLocal() as db:
        user = db.get(User, ids["user_id"])
        assert user is not None
        context = attested_user_context(user, organization_id=ids["organization_id"])

    with SessionLocal() as db:
        deal = db.get(Deal, ids["deal_id"])
        assert deal is not None
        decision = authorize_execution(
            db,
            ExecutionRequest(
                organization_id=ids["organization_id"],
                capability_key=AUTOMATION_DEAL_CREATED_RULES,
                actor=context,
                resource_type="deal",
                resource_id=str(deal.id),
                resource_organization_id=deal.organization_id,
                resource_active=True,
                required_permission="deals.delete_everything",
            ),
        )
        db.commit()
    assert decision.allowed is False
    assert decision.reason_code == "actor_not_authorized"


# --- Target resource -----------------------------------------------------------------------------


def test_a_target_from_another_organization_is_refused() -> None:
    ids = _scenario()
    with SessionLocal() as db:
        user = db.get(User, ids["user_id"])
        assert user is not None
        decision = authorize_execution(
            db,
            ExecutionRequest(
                organization_id=ids["organization_id"],
                capability_key=AUTOMATION_DEAL_CREATED_RULES,
                actor=attested_user_context(user, organization_id=ids["organization_id"]),
                resource_type="deal",
                resource_id=str(uuid4()),
                resource_organization_id=uuid4(),
                resource_active=True,
                required_permission=None,
            ),
        )
        db.commit()
    assert decision.reason_code == "target_organization_mismatch"


def test_a_draft_or_paused_rule_never_executes() -> None:
    for status in (AutomationRule.STATUS_DRAFT, AutomationRule.STATUS_DISABLED):
        ids = _scenario(rule_status=status)
        assert _run(ids) == []
        assert _execution_count(ids["organization_id"]) == 0


def test_another_organizations_deal_cannot_be_executed() -> None:
    ids = _scenario()
    other = _scenario()
    with SessionLocal() as db:
        deal = db.get(Deal, other["deal_id"])
        user = db.get(User, ids["user_id"])
        assert deal is not None and user is not None
        with pytest.raises(ValueError):
            execute_deal_created_automations(
                db,
                organization_id=ids["organization_id"],
                deal=deal,
                user_context=attested_user_context(user, organization_id=ids["organization_id"]),
            )


# --- Budget, approval, provider and consent gates -------------------------------------------------


def test_billable_work_without_a_budget_reservation_is_denied() -> None:
    ids = _scenario()
    with SessionLocal() as db:
        user = db.get(User, ids["user_id"])
        assert user is not None
        decision = authorize_execution(
            db,
            ExecutionRequest(
                organization_id=ids["organization_id"],
                capability_key=AUTOMATION_DEAL_CREATED_RULES,
                actor=attested_user_context(user, organization_id=ids["organization_id"]),
                resource_type="deal",
                resource_id=str(uuid4()),
                resource_organization_id=ids["organization_id"],
                resource_active=True,
                required_permission=None,
                billable=True,
            ),
        )
        db.commit()
    assert decision.reason_code == "budget_reservation_required"


def test_a_capability_that_needs_approval_denies_because_no_approval_exists(monkeypatch) -> None:
    ids = _scenario()
    original = CAPABILITY_BY_KEY[AUTOMATION_DEAL_CREATED_RULES]
    monkeypatch.setitem(
        CAPABILITY_BY_KEY,
        AUTOMATION_DEAL_CREATED_RULES,
        replace(original, requires_approval=True),
    )

    assert _run(ids) == []
    assert _denied_reasons(ids["organization_id"]) == ["approval_not_available"]


def test_a_provider_requirement_denies_while_no_provider_connection_exists(monkeypatch) -> None:
    ids = _scenario()
    original = CAPABILITY_BY_KEY[AUTOMATION_DEAL_CREATED_RULES]
    monkeypatch.setitem(
        CAPABILITY_BY_KEY,
        AUTOMATION_DEAL_CREATED_RULES,
        replace(original, requires_provider=True),
    )

    assert _run(ids) == []
    assert _denied_reasons(ids["organization_id"]) == ["provider_not_connected"]


def test_a_consent_requirement_denies_while_no_consent_model_exists(monkeypatch) -> None:
    ids = _scenario()
    original = CAPABILITY_BY_KEY[AUTOMATION_DEAL_CREATED_RULES]
    monkeypatch.setitem(
        CAPABILITY_BY_KEY,
        AUTOMATION_DEAL_CREATED_RULES,
        replace(original, requires_consent=True),
    )

    assert _run(ids) == []
    assert _denied_reasons(ids["organization_id"]) == ["consent_not_configured"]


def test_an_ai_capability_without_a_confirmed_plan_feature_never_runs() -> None:
    with SessionLocal() as db:
        user, organization = create_authorized_user(db)
        for key in (AI_MASTER, "ai.assistant"):
            set_capability_enabled(
                db,
                organization_id=organization.id,
                actor_user_id=user.id,
                capability_key=key,
                is_enabled=True,
            )
        db.commit()
        decision = evaluate_capability(
            db,
            organization_id=organization.id,
            capability_key="ai.assistant",
            user_context=attested_user_context(user, organization_id=organization.id),
        )
    assert decision.allowed is False
    assert decision.reason_code == "entitlement_not_defined"


# --- In-flight revalidation -----------------------------------------------------------------------


def _patch_action_hook(monkeypatch, hook: Callable[[], None]) -> None:
    """Run ``hook`` after each action, to change governance state mid-run."""
    original = execution_service._execute_action

    def wrapped(db, **kwargs):
        result = original(db, **kwargs)
        hook()
        return result

    monkeypatch.setattr(execution_service, "_execute_action", wrapped)


def test_turning_automation_off_mid_run_stops_the_remaining_rules(monkeypatch) -> None:
    ids = _scenario(rule_count=3)
    fired = {"count": 0}

    def disable_after_first() -> None:
        fired["count"] += 1
        if fired["count"] == 1:
            with SessionLocal() as db:
                set_capability_enabled(
                    db,
                    organization_id=ids["organization_id"],
                    actor_user_id=ids["user_id"],
                    capability_key=AUTOMATION_MASTER,
                    is_enabled=False,
                )
                db.commit()

    _patch_action_hook(monkeypatch, disable_after_first)

    with SessionLocal() as db:
        deal = db.get(Deal, ids["deal_id"])
        user = db.get(User, ids["user_id"])
        assert deal is not None and user is not None
        executions = execute_deal_created_automations(
            db,
            organization_id=ids["organization_id"],
            deal=deal,
            user_context=attested_user_context(user, organization_id=ids["organization_id"]),
        )
        db.commit()

    assert len(executions) == 1
    assert _execution_count(ids["organization_id"]) == 1
    assert _denied_reasons(ids["organization_id"]) == ["master_disabled"]


def test_pausing_a_rule_mid_run_stops_it_and_later_rules_still_run_when_allowed(monkeypatch) -> None:
    ids = _scenario(rule_count=3)
    paused = ids["rule_ids"][1]
    fired = {"count": 0}

    def pause_second_rule() -> None:
        fired["count"] += 1
        if fired["count"] == 1:
            with SessionLocal() as db:
                rule = db.get(AutomationRule, paused)
                assert rule is not None
                rule.status = AutomationRule.STATUS_DISABLED
                db.commit()

    _patch_action_hook(monkeypatch, pause_second_rule)

    with SessionLocal() as db:
        deal = db.get(Deal, ids["deal_id"])
        user = db.get(User, ids["user_id"])
        assert deal is not None and user is not None
        executions = execute_deal_created_automations(
            db,
            organization_id=ids["organization_id"],
            deal=deal,
            user_context=attested_user_context(user, organization_id=ids["organization_id"]),
        )
        db.commit()

    # The paused rule is refused and the run stops there, so the third rule does not run either.
    assert len(executions) == 1
    assert _denied_reasons(ids["organization_id"]) == ["resource_not_active"]


def test_revalidation_happens_before_every_action_not_only_every_rule(monkeypatch) -> None:
    ids = _scenario(rule_count=1, action_count=2)
    fired = {"count": 0}

    def disable_after_first_action() -> None:
        fired["count"] += 1
        if fired["count"] == 1:
            with SessionLocal() as db:
                set_capability_enabled(
                    db,
                    organization_id=ids["organization_id"],
                    actor_user_id=ids["user_id"],
                    capability_key=AUTOMATION_MASTER,
                    is_enabled=False,
                )
                db.commit()

    _patch_action_hook(monkeypatch, disable_after_first_action)

    executions = _run(ids)

    assert len(executions) == 1
    with SessionLocal() as db:
        execution = db.scalar(
            select(AutomationExecution).where(
                AutomationExecution.organization_id == ids["organization_id"]
            )
        )
        assert execution is not None
        statuses = [item["status"] for item in execution.action_results]
    # The first action ran. The second was stopped by the gate before it executed.
    assert statuses == ["SUCCEEDED", "SKIPPED"]
    assert execution.status == AutomationExecution.STATUS_PARTIAL
    stages = [audit["metadata"]["stage"] for audit in _gate_audits(ids["organization_id"])]
    assert stages == ["initial", "action", "action"]
    assert _denied_reasons(ids["organization_id"]) == ["master_disabled"]


def test_a_null_or_empty_feature_key_can_never_grant_access(monkeypatch) -> None:
    ids = _scenario()
    original = CAPABILITY_BY_KEY[AUTOMATION_DEAL_CREATED_RULES]
    # A snapshot that lists null and empty feature keys as enabled must not satisfy the gate.
    permissive = [
        {"feature_key": None, "enabled": True},
        {"feature_key": "", "enabled": True},
        {"enabled": True},
    ]
    for feature in (None, ""):
        monkeypatch.setitem(
            CAPABILITY_BY_KEY,
            AUTOMATION_DEAL_CREATED_RULES,
            replace(original, entitlement_feature=feature),
        )
        assert _run(ids, context_kwargs={"entitlements": permissive}) == []
    assert _denied_reasons(ids["organization_id"]) == ["entitlement_not_defined", "entitlement_not_defined"]


def test_each_later_step_is_revalidated_and_audited() -> None:
    ids = _scenario(rule_count=2)

    executions = _run(ids)

    assert len(executions) == 2
    stages = sorted(audit["metadata"]["stage"] for audit in _gate_audits(ids["organization_id"]))
    # One initial check, one action check per action, and one revalidation before the second rule.
    assert stages == sorted(["initial", "action", "revalidation", "action"])


# --- Audit, allowed and denied -----------------------------------------------------------------


def test_allowed_and_denied_decisions_are_both_audited_with_the_reason() -> None:
    ids = _scenario()
    _run(ids)
    _set(ids, AUTOMATION_MASTER, False)
    _run(ids)

    audits = _gate_audits(ids["organization_id"])
    decisions = [audit["decision"] for audit in audits]
    # The allowed run records the initial check and its one action. The denied run records one check.
    assert decisions == ["allowed", "allowed", "denied"]
    assert audits[0]["resource_type"] == "deal"
    assert audits[-1]["metadata"]["reason_code"] == "master_disabled"
    # Only the fields below are ever written. No payload, no names, no personal data.
    for audit in audits:
        assert set(audit["metadata"]) == {
            "capability_key",
            "reason_code",
            "stage",
            "policy_version",
            "billable",
            "budget_unit",
        }


