"""SIBVO entitlement enforcement at the deal-created automation entry point (decision 3).

Each negative case proves two things: the policy returns the stable reason code, and the
entry point creates no execution. Manual CRM is checked separately: a denied automation never
blocks deal creation.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.automation_rules.execution_service import execute_deal_created_automations
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.db.models.organization import Organization
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES, AUTOMATION_MASTER
from app.governance.policy import (
    REASON_CAPABILITY_DISABLED,
    REASON_MASTER_DISABLED,
    evaluate_capability,
)
from app.governance.service import set_capability_enabled
from tests.governance_helpers import attested_user_context
from tests.test_automation_execution_service import create_test_deal
from tests.test_deals_api import (
    create_authorized_user,
    create_customer_profile,
    create_lead,
    create_property,
    valid_payload,
)
from tests.test_team_api import create_manager

RULE_CONDITIONS = [{"field": "stage", "operator": "equals", "value": "NEW"}]
RULE_ACTIONS = [{"type": "CREATE_FOLLOW_UP", "config": {"title": "Call", "due_in_days": 1}}]


@pytest.fixture
def scenario() -> Iterator[dict]:
    """An organization with a matching active rule, a deal, and both switches on."""
    with SessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(db, user=user, organization=organization, lead_id=lead.id)
        db.add(
            AutomationRule(
                organization_id=organization.id,
                name="Entitlement test rule",
                description="Entitlement enforcement",
                trigger_type="DEAL_CREATED",
                trigger_config={},
                conditions=RULE_CONDITIONS,
                actions=RULE_ACTIONS,
                status=AutomationRule.STATUS_ACTIVE,
                created_by_user_id=user.id,
            )
        )
        for key in (AUTOMATION_MASTER, AUTOMATION_DEAL_CREATED_RULES):
            set_capability_enabled(
                db,
                organization_id=organization.id,
                actor_user_id=user.id,
                capability_key=key,
                is_enabled=True,
            )
        db.commit()
        values = {"user_id": user.id, "organization_id": organization.id, "deal_id": deal.id}
    yield values
    with SessionLocal() as db:
        db.execute(delete(AutomationExecution).where(
            AutomationExecution.rule_id.in_(
                select(AutomationRule.id).where(AutomationRule.organization_id == values["organization_id"])
            )
        ))
        db.execute(delete(OrganizationCapabilitySetting).where(
            OrganizationCapabilitySetting.organization_id == values["organization_id"]
        ))
        db.commit()


def _context(scenario: dict, **overrides) -> CurrentUserContext | None:
    with SessionLocal() as db:
        user = db.get(User, scenario["user_id"])
        assert user is not None
        return attested_user_context(user, organization_id=scenario["organization_id"], **overrides)


def _run(scenario: dict, context: CurrentUserContext | None) -> int:
    with SessionLocal() as db:
        deal = db.get(Deal, scenario["deal_id"])
        executions = execute_deal_created_automations(
            db,
            organization_id=scenario["organization_id"],
            deal=deal,
            user_context=context,
        )
        db.commit()
        return len(executions)


def _decision(scenario: dict, context: CurrentUserContext | None):
    with SessionLocal() as db:
        return evaluate_capability(
            db,
            organization_id=scenario["organization_id"],
            capability_key=AUTOMATION_DEAL_CREATED_RULES,
            user_context=context,
        )


def _execution_count(scenario: dict) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(AutomationExecution)
            .join(AutomationRule, AutomationRule.id == AutomationExecution.rule_id)
            .where(AutomationRule.organization_id == scenario["organization_id"])
        )


def test_all_gates_satisfied_allows_the_rule_to_run(scenario) -> None:
    assert _decision(scenario, _context(scenario)).allowed is True
    assert _run(scenario, _context(scenario)) == 1


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"entitlements": ({"feature_key": "other", "enabled": True},)}, "entitlement_missing"),
        ({"entitlements": ({"feature_key": "workflow_automation", "enabled": False},)}, "entitlement_disabled"),
        ({"subscription_status": "expired"}, "trial_expired"),
        ({"subscription_status": "past_due"}, "subscription_not_active"),
        ({"product_role": None}, "product_membership_inactive"),
        ({"sibvo_attested": False}, "entitlement_unverified"),
        ({"entitlements": "not-a-list"}, "entitlement_unverified"),
        ({"entitlements": ("not-an-object",)}, "entitlement_unverified"),
        ({"session_organization_id": uuid4()}, "wrong_organization"),
        ({"sibvo_organization_id": uuid4()}, "wrong_organization"),
    ],
)
def test_each_failed_entitlement_denies_with_a_stable_reason_and_creates_nothing(
    scenario, overrides, expected_reason
) -> None:
    with SessionLocal() as db:
        user = db.get(User, scenario["user_id"])
        context = attested_user_context(user, organization_id=scenario["organization_id"], **overrides)

    decision = _decision(scenario, context)

    assert decision.allowed is False
    assert decision.reason_code == expected_reason
    assert _run(scenario, context) == 0
    assert _execution_count(scenario) == 0


def test_revoked_access_with_no_snapshot_is_denied(scenario) -> None:
    decision = _decision(scenario, None)

    assert decision.allowed is False
    assert decision.reason_code == "entitlement_unverified"
    assert _run(scenario, None) == 0


def test_sibvo_unavailable_fails_closed(scenario) -> None:
    # SIBVO unavailable means no verified snapshot reaches the gate.
    context = _context(scenario, sibvo_attested=False)

    assert _decision(scenario, context).reason_code == "entitlement_unverified"
    assert _run(scenario, context) == 0


def test_organization_automation_disabled_is_denied_even_with_entitlement(scenario) -> None:
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=scenario["organization_id"],
            actor_user_id=scenario["user_id"],
            capability_key=AUTOMATION_MASTER,
            is_enabled=False,
        )
        db.commit()

    decision = _decision(scenario, _context(scenario))

    assert decision.reason_code == REASON_MASTER_DISABLED
    assert _run(scenario, _context(scenario)) == 0


def test_child_capability_disabled_is_denied_even_with_entitlement(scenario) -> None:
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=scenario["organization_id"],
            actor_user_id=scenario["user_id"],
            capability_key=AUTOMATION_DEAL_CREATED_RULES,
            is_enabled=False,
        )
        db.commit()

    decision = _decision(scenario, _context(scenario))

    assert decision.reason_code == REASON_CAPABILITY_DISABLED
    assert _run(scenario, _context(scenario)) == 0


def test_inactive_rule_does_not_execute_even_when_every_gate_passes(scenario) -> None:
    with SessionLocal() as db:
        db.execute(
            AutomationRule.__table__.update()
            .where(AutomationRule.organization_id == scenario["organization_id"])
            .values(status=AutomationRule.STATUS_DRAFT)
        )
        db.commit()

    assert _run(scenario, _context(scenario)) == 0
    assert _execution_count(scenario) == 0


def test_unauthorized_actor_cannot_create_the_deal_so_nothing_runs(scenario) -> None:
    viewer, organization = create_manager(permissions=("deals.read",))
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user_context] = lambda: attested_user_context(
        viewer, organization_id=organization.id
    )
    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.post("/api/v1/deals", json=valid_payload(
            customer_profile_id=uuid4(), property_id=uuid4(), lead_id=None,
        ))
    assert response.status_code == 403


def test_denied_automation_never_blocks_manual_deal_creation(scenario) -> None:
    from app.main import create_app

    with SessionLocal() as db:
        db.expire_on_commit = False
        user = db.get(User, scenario["user_id"])
        organization = db.get(Organization, scenario["organization_id"])
        lead = create_lead(db, organization=organization)
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()
        customer_id, property_id, lead_id = customer.id, property_record.id, lead.id

    app = create_app()
    app.dependency_overrides[get_current_user_context] = lambda: attested_user_context(
        user, organization_id=scenario["organization_id"],
        entitlements=({"feature_key": "workflow_automation", "enabled": False},),
    )
    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(scenario["organization_id"])})
        response = client.post("/api/v1/deals", json=valid_payload(
            customer_profile_id=customer_id, property_id=property_id, lead_id=lead_id,
        ))

    assert response.status_code == 201, response.text
    assert _execution_count(scenario) == 0

