
"""End-to-end tests for deal-created automation execution."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.follow_up import FollowUp
from app.db.session import SessionLocal
from tests.governance_helpers import enable_deal_created_automation
from tests.test_deals_api import (
    create_authorized_user,
    create_customer_profile,
    create_lead,
    create_property,
    create_test_app,
    valid_payload,
)

TestingSessionLocal = SessionLocal


def test_creating_deal_through_api_executes_active_automation() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(
            db,
            organization=organization,
        )
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        enable_deal_created_automation(
            db,
            organization_id=organization.id,
            actor_user_id=user.id,
        )

        rule = AutomationRule(
            organization_id=organization.id,
            name="Create follow-up for new deals",
            description="Integration test",
            trigger_type="DEAL_CREATED",
            trigger_config={},
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
                        "title": "API-created automation follow-up",
                    },
                }
            ],
            status=AutomationRule.STATUS_ACTIVE,
            created_by_user_id=user.id,
        )
        db.add(rule)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
            lead_id=lead.id,
        )

        app = create_test_app(user=user)
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 201, response.text
        deal_id = response.json()["id"]

        db.expire_all()

        execution = db.scalar(
            select(AutomationExecution).where(
                AutomationExecution.organization_id == organization.id,
                AutomationExecution.rule_id == rule.id,
                AutomationExecution.event_id == deal_id,
                AutomationExecution.event_type == "DEAL_CREATED",
            )
        )

        assert execution is not None
        assert execution.status == AutomationExecution.STATUS_SUCCEEDED
        assert execution.completed_at is not None
        assert len(execution.action_results) == 1

        action_result = execution.action_results[0]
        assert action_result["action_type"] == "CREATE_FOLLOW_UP"
        assert action_result["status"] == "SUCCEEDED"

        follow_up = db.scalar(
            select(FollowUp).where(
                FollowUp.organization_id == organization.id,
                FollowUp.lead_id == lead.id,
                FollowUp.title == "API-created automation follow-up",
            )
        )

        assert follow_up is not None
        assert follow_up.owner_user_id == user.id
        assert follow_up.status == FollowUp.STATUS_PENDING


def test_creating_deal_with_nonmatching_rule_records_skipped_execution() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(
            db,
            organization=organization,
        )
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        enable_deal_created_automation(
            db,
            organization_id=organization.id,
            actor_user_id=user.id,
        )

        rule = AutomationRule(
            organization_id=organization.id,
            name="Only negotiate deals",
            description="Nonmatching integration test",
            trigger_type="DEAL_CREATED",
            trigger_config={},
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
            status=AutomationRule.STATUS_ACTIVE,
            created_by_user_id=user.id,
        )
        db.add(rule)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
            lead_id=lead.id,
        )

        app = create_test_app(user=user)
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 201, response.text
        deal_id = response.json()["id"]

        db.expire_all()

        execution = db.scalar(
            select(AutomationExecution).where(
                AutomationExecution.organization_id == organization.id,
                AutomationExecution.rule_id == rule.id,
                AutomationExecution.event_id == deal_id,
            )
        )

        assert execution is not None
        assert execution.status == AutomationExecution.STATUS_SKIPPED

        follow_ups = db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == organization.id,
                FollowUp.lead_id == lead.id,
            )
        ).all()

        assert follow_ups == []
