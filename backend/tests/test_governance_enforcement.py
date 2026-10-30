"""Governance enforcement at the deal-created automation entry point (DFR1-006).

The rule is active and its condition matches, so any execution here is caused only by
the governance switches. A denied automation must leave the deal itself untouched.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from app.automation_rules.execution_service import execute_deal_created_automations
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES, AUTOMATION_MASTER
from app.governance.service import set_capability_enabled
from tests.governance_helpers import attested_user_context
from tests.test_automation_execution_service import create_test_deal
from tests.test_deals_api import create_authorized_user, create_lead

MATCHING_CONDITIONS = [{"field": "stage", "operator": "equals", "value": "NEW"}]
FOLLOW_UP_ACTION = [
    {
        "type": "CREATE_FOLLOW_UP",
        "config": {"title": "Call the new lead", "due_in_days": 1},
    }
]


def _seed() -> tuple[UUID, UUID, UUID]:
    """Create a user, organization, deal and matching active rule. Return their IDs."""
    with SessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(db, user=user, organization=organization, lead_id=lead.id)
        db.add(
            AutomationRule(
                organization_id=organization.id,
                name="Governance test rule",
                description="Governance enforcement",
                trigger_type="DEAL_CREATED",
                trigger_config={},
                conditions=MATCHING_CONDITIONS,
                actions=FOLLOW_UP_ACTION,
                status=AutomationRule.STATUS_ACTIVE,
                created_by_user_id=user.id,
            )
        )
        db.commit()
        return user.id, organization.id, deal.id


def _set(user_id: UUID, organization_id: UUID, key: str, enabled: bool) -> None:
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            capability_key=key,
            is_enabled=enabled,
        )
        db.commit()


def _run(user_id: UUID, organization_id: UUID, deal_id: UUID) -> int:
    """Run the deal-created automations and return how many executions were created."""
    with SessionLocal() as db:
        deal = db.get(Deal, deal_id)
        user = db.get(User, user_id)
        assert deal is not None and user is not None
        executions = execute_deal_created_automations(
            db,
            organization_id=organization_id,
            deal=deal,
            user_context=attested_user_context(user, organization_id=organization_id),
        )
        db.commit()
        return len(executions)


def _execution_count(organization_id: UUID) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(AutomationExecution)
            .join(AutomationRule, AutomationRule.id == AutomationExecution.rule_id)
            .where(AutomationRule.organization_id == organization_id)
        )


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization_id
            )
        )
        db.commit()


def test_no_rule_runs_while_automation_is_disabled_by_default() -> None:
    user_id, organization_id, deal_id = _seed()
    try:
        assert _run(user_id, organization_id, deal_id) == 0
        assert _execution_count(organization_id) == 0
        with SessionLocal() as db:
            # Manual CRM data is untouched by a denied automation.
            assert db.get(Deal, deal_id) is not None
    finally:
        _cleanup(organization_id)


def test_child_switch_alone_does_not_allow_execution() -> None:
    user_id, organization_id, deal_id = _seed()
    try:
        _set(user_id, organization_id, AUTOMATION_DEAL_CREATED_RULES, True)
        assert _run(user_id, organization_id, deal_id) == 0
        assert _execution_count(organization_id) == 0
    finally:
        _cleanup(organization_id)


def test_both_switches_on_allows_the_matching_rule_to_run() -> None:
    user_id, organization_id, deal_id = _seed()
    try:
        _set(user_id, organization_id, AUTOMATION_MASTER, True)
        _set(user_id, organization_id, AUTOMATION_DEAL_CREATED_RULES, True)
        assert _run(user_id, organization_id, deal_id) == 1
        assert _execution_count(organization_id) == 1
    finally:
        _cleanup(organization_id)


def test_disabling_the_master_stops_new_executions_immediately() -> None:
    user_id, organization_id, deal_id = _seed()
    try:
        _set(user_id, organization_id, AUTOMATION_MASTER, True)
        _set(user_id, organization_id, AUTOMATION_DEAL_CREATED_RULES, True)
        _set(user_id, organization_id, AUTOMATION_MASTER, False)
        assert _run(user_id, organization_id, deal_id) == 0
    finally:
        _cleanup(organization_id)
