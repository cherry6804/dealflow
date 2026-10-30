
"""Tests for the tenant-scoped automation execution service."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automation_rules.execution_service import (
    execute_deal_created_automations,
)
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import SessionLocal
from tests.governance_helpers import enable_deal_created_automation
from tests.test_deals_api import (
    create_authorized_user,
    create_customer_profile,
    create_lead,
    create_property,
)
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationPreference
from app.notifications.service import get_or_create_notification_preferences

TestingSessionLocal = SessionLocal


def create_test_deal(
    db: Session,
    *,
    user: User,
    organization: Organization,
    lead_id=None,
) -> Deal:
    """Create a deal belonging to the supplied organization."""
    customer = create_customer_profile(
        db,
        organization=organization,
    )
    property_record = create_property(
        db,
        organization=organization,
    )

    deal = Deal(
        organization_id=organization.id,
        customer_profile_id=customer.id,
        property_id=property_record.id,
        lead_id=lead_id,
        owner_user_id=user.id,
        stage=Deal.STAGE_NEW,
        expected_value=Decimal("7500000.00"),
        currency="INR",
        notes="Automation execution test",
    )
    db.add(deal)
    db.flush()
    return deal


def create_active_rule(
    db: Session,
    *,
    user: User,
    organization: Organization,
    conditions: list[dict],
    actions: list[dict],
    trigger_type: str = "DEAL_CREATED",
) -> AutomationRule:
    """Create an active automation rule directly in the database."""
    rule = AutomationRule(
        organization_id=organization.id,
        name=f"Test automation {uuid4()}",
        description="Execution-service test rule",
        trigger_type=trigger_type,
        trigger_config={},
        conditions=conditions,
        actions=actions,
        status=AutomationRule.STATUS_ACTIVE,
        created_by_user_id=user.id,
    )
    db.add(rule)
    db.flush()
    enable_deal_created_automation(
        db,
        organization_id=organization.id,
        actor_user_id=user.id,
    )
    return rule


def test_matching_rule_creates_follow_up() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
            lead_id=lead.id,
        )
        rule = create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[
                {
                    "field": "stage",
                    "operator": "equals",
                    "value": "NEW",
                }
            ],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {
                        "days_after": 1,
                        "title": "Automation-created follow-up",
                    },
                }
            ],
        )
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )
        db.flush()

        assert len(executions) == 1
        execution = executions[0]
        assert execution.rule_id == rule.id
        assert execution.event_id == deal.id
        assert execution.event_type == "DEAL_CREATED"
        assert execution.status == AutomationExecution.STATUS_SUCCEEDED
        assert execution.completed_at is not None

        result = execution.action_results[0]
        assert result["action_type"] == "CREATE_FOLLOW_UP"
        assert result["status"] == "SUCCEEDED"

        follow_up = db.scalar(
            select(FollowUp).where(
                FollowUp.id == result["follow_up_id"],
                FollowUp.organization_id == organization.id,
            )
        )
        assert follow_up is not None
        assert follow_up.lead_id == lead.id
        assert follow_up.owner_user_id == user.id
        assert follow_up.title == "Automation-created follow-up"
        assert follow_up.status == FollowUp.STATUS_PENDING

        db.commit()


def test_non_matching_rule_is_skipped() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
            lead_id=lead.id,
        )
        create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[
                {
                    "field": "stage",
                    "operator": "equals",
                    "value": "NEGOTIATION",
                }
            ],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {"days_after": 1},
                }
            ],
        )
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )

        assert len(executions) == 1
        assert executions[0].status == AutomationExecution.STATUS_SKIPPED
        assert executions[0].action_results[0]["status"] == "SKIPPED"

        follow_ups = db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == organization.id,
            )
        ).all()
        assert follow_ups == []

        db.commit()


def test_follow_up_action_is_skipped_when_deal_has_no_lead() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
        )
        create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {"days_after": 1},
                }
            ],
        )
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )

        assert len(executions) == 1
        assert executions[0].status == AutomationExecution.STATUS_SKIPPED
        assert executions[0].action_results[0]["status"] == "SKIPPED"
        assert "no linked lead" in executions[0].action_results[0]["reason"]

        db.commit()


def test_unsupported_action_records_failed_execution() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
        )
        create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[{"type": "UNSUPPORTED_ACTION", "config": {}}],
        )
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )

        assert len(executions) == 1
        execution = executions[0]
        assert execution.status == AutomationExecution.STATUS_FAILED
        assert execution.error_message is not None
        assert execution.action_results[0]["status"] == "FAILED"
        assert "Unsupported automation action" in (
            execution.action_results[0]["reason"]
        )

        db.commit()


def test_rules_from_another_organization_are_not_executed() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(db)
        user_b, organization_b = create_authorized_user(db)

        deal_a = create_test_deal(
            db,
            user=user_a,
            organization=organization_a,
        )
        create_active_rule(
            db,
            user=user_b,
            organization=organization_b,
            conditions=[],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {"days_after": 1},
                }
            ],
        )
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization_a.id,
            deal=deal_a,
        )

        assert executions == []

        cross_tenant_executions = db.scalars(
            select(AutomationExecution).where(
                AutomationExecution.organization_id == organization_b.id,
                AutomationExecution.event_id == deal_a.id,
            )
        ).all()
        assert cross_tenant_executions == []


def test_execution_rejects_deal_from_another_organization() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(db)
        user_b, organization_b = create_authorized_user(db)

        deal_b = create_test_deal(
            db,
            user=user_b,
            organization=organization_b,
        )
        db.commit()

        with pytest.raises(
            ValueError,
            match="does not belong to the requested organization",
        ):
            execute_deal_created_automations(
                db,
                organization_id=organization_a.id,
                deal=deal_b,
            )


def test_malformed_condition_field_records_failed_execution() -> None:
    """A non-string condition field must not crash automation processing."""
    from app.automation_rules.execution_service import (
        _evaluate_conditions,
        AutomationConditionError,
    )

    deal = Deal(
        organization_id=uuid4(),
        stage="NEW",
        expected_value=100000,
        currency="INR",
    )

    with pytest.raises(AutomationConditionError):
        _evaluate_conditions(
            [{"field": [], "operator": "equals", "value": "NEW"}],
            deal,
        )


def test_malformed_condition_operator_is_rejected() -> None:
    """A non-string condition operator must be rejected safely."""
    from app.automation_rules.execution_service import (
        _evaluate_conditions,
        AutomationConditionError,
    )

    deal = Deal(
        organization_id=uuid4(),
        stage="NEW",
        expected_value=100000,
        currency="INR",
    )

    with pytest.raises(AutomationConditionError):
        _evaluate_conditions(
            [{"field": "stage", "operator": [], "value": "NEW"}],
            deal,
        )


def test_exists_condition_requires_explicit_boolean_value() -> None:
    """The exists operator must reject a missing value."""
    from app.automation_rules.execution_service import (
        _evaluate_conditions,
        AutomationConditionError,
    )

    deal = Deal(
        organization_id=uuid4(),
        stage="NEW",
        expected_value=100000,
        currency="INR",
    )

    with pytest.raises(AutomationConditionError):
        _evaluate_conditions(
            [{"field": "lead_id", "operator": "exists"}],
            deal,
        )


def test_successful_execution_creates_notification_for_rule_creator() -> None:
    """A successful execution notifies the automation rule creator."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
            lead_id=lead.id,
        )
        rule = create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {
                        "days_after": 1,
                        "title": "Notification test follow-up",
                    },
                }
            ],
        )
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )
        db.flush()

        assert len(executions) == 1
        execution = executions[0]
        assert execution.status == AutomationExecution.STATUS_SUCCEEDED

        notification = db.scalar(
            select(Notification).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_type == "AUTOMATION_EXECUTION_SUCCEEDED",
                Notification.resource_type == "automation_execution",
                Notification.resource_id == str(execution.id),
            )
        )

        assert notification is not None
        assert notification.title == "Automation completed"
        assert rule.name in notification.message
        assert str(deal.id) in notification.message
        assert (
            notification.event_key
            == f"automation-execution:{execution.id}:completed"
        )

        db.commit()


def test_automation_execution_notification_respects_disabled_preference() -> None:
    """Disabling automation notifications suppresses execution notifications."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
            lead_id=lead.id,
        )
        create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {"days_after": 1},
                }
            ],
        )

        preference = get_or_create_notification_preferences(
            db,
            organization_id=organization.id,
            user_id=user.id,
        )
        preference.automation_enabled = False
        db.commit()

        executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )
        db.flush()

        assert len(executions) == 1
        assert executions[0].status == AutomationExecution.STATUS_SUCCEEDED

        notification = db.scalar(
            select(Notification.id).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_type == "AUTOMATION_EXECUTION_SUCCEEDED",
            )
        )
        assert notification is None

        db.commit()


def test_repeated_deal_created_event_does_not_duplicate_execution_notification() -> None:
    """Retrying an event doesn't create another execution notification."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(
            db,
            user=user,
            organization=organization,
            lead_id=lead.id,
        )
        create_active_rule(
            db,
            user=user,
            organization=organization,
            conditions=[],
            actions=[
                {
                    "type": "CREATE_FOLLOW_UP",
                    "config": {"days_after": 1},
                }
            ],
        )
        db.commit()

        first_executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )
        db.commit()

        assert len(first_executions) == 1

        second_executions = execute_deal_created_automations(
            db,
            organization_id=organization.id,
            deal=deal,
        )
        db.commit()

        assert second_executions == []

        notifications = db.scalars(
            select(Notification).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_type == "AUTOMATION_EXECUTION_SUCCEEDED",
                Notification.resource_id == str(first_executions[0].id),
            )
        ).all()

        assert len(notifications) == 1
