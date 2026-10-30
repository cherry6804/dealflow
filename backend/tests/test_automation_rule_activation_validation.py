"""Regression tests for automation-rule activation validation."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest

from app.db.models.automation_rule import AutomationRule
from tests.test_automation_rules_api import (
    ALL_PERMISSIONS,
    TestingSessionLocal,
    create_authorized_user,
    create_rule,
    request_as,
    valid_payload,
)


@pytest.mark.parametrize(
    ("change", "expected_detail"),
    [
        (
            lambda payload: payload.update(
                {"trigger_type": "FOLLOW_UP_OVERDUE"}
            ),
            "unsupported trigger",
        ),
        (
            lambda payload: payload.update(
                {"trigger_config": {"unknown_option": True}}
            ),
            "trigger configuration",
        ),
        (
            lambda payload: payload.update(
                {"trigger_config": {"source": "customers"}}
            ),
            "trigger source",
        ),
        (
            lambda payload: payload.update(
                {"trigger_config": {"source": []}}
            ),
            "trigger source",
        ),
        (
            lambda payload: payload.update(
                {"trigger_config": {"source": {}}}
            ),
            "trigger source",
        ),
        (
            lambda payload: payload.update(
                {
                    "conditions": [
                        {
                            "field": "unsupported_field",
                            "operator": "equals",
                            "value": "NEW",
                        }
                    ]
                }
            ),
            "unsupported field",
        ),
        (
            lambda payload: payload.update(
                {
                    "conditions": [
                        {
                            "field": "stage",
                            "operator": "unsupported_operator",
                            "value": "NEW",
                        }
                    ]
                }
            ),
            "unsupported operator",
        ),
        (
            lambda payload: payload.update(
                {
                    "conditions": [
                        {
                            "field": "stage",
                            "operator": "equals",
                        }
                    ]
                }
            ),
            "must include a value",
        ),
        (
            lambda payload: payload.update(
                {
                    "conditions": [
                        {
                            "field": "stage",
                            "operator": "in",
                            "value": "NEW",
                        }
                    ]
                }
            ),
            "must use a list",
        ),
        (
            lambda payload: payload.update(
                {
                    "conditions": [
                        {
                            "field": "stage",
                            "operator": "exists",
                            "value": "true",
                        }
                    ]
                }
            ),
            "boolean value",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "SEND_EMAIL",
                            "config": {},
                        }
                    ]
                }
            ),
            "unsupported type",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "CREATE_FOLLOW_UP",
                            "config": {"days_after": True},
                        }
                    ]
                }
            ),
            "days_after",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "CREATE_FOLLOW_UP",
                            "config": {"days_after": -1},
                        }
                    ]
                }
            ),
            "days_after",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "CREATE_FOLLOW_UP",
                            "config": {"days_after": 3651},
                        }
                    ]
                }
            ),
            "days_after",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "CREATE_FOLLOW_UP",
                            "config": {"follow_up_type": "INVALID"},
                        }
                    ]
                }
            ),
            "follow-up configuration",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "CREATE_FOLLOW_UP",
                            "config": {"title": "   "},
                        }
                    ]
                }
            ),
            "follow-up configuration",
        ),
        (
            lambda payload: payload.update(
                {
                    "actions": [
                        {
                            "type": "CREATE_FOLLOW_UP",
                            "config": {"unexpected": "value"},
                        }
                    ]
                }
            ),
            "unsupported configuration",
        ),
    ],
)
def test_invalid_rule_configuration_is_rejected_without_activation(
    change,
    expected_detail: str,
) -> None:
    """Invalid configurations return 409 and leave the rule in DRAFT."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        payload = deepcopy(valid_payload())
        change(payload)

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client, payload)

            response = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )

        assert response.status_code == 409, response.text
        assert expected_detail in response.json()["detail"].lower()

        db.expire_all()
        persisted = db.get(AutomationRule, UUID(created["id"]))

        assert persisted is not None
        assert persisted.status == AutomationRule.STATUS_DRAFT


def test_valid_follow_up_rule_can_be_activated() -> None:
    """A supported deal-created follow-up rule remains activatable."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        payload = valid_payload()
        payload["trigger_config"] = {"source": "deals"}
        payload["conditions"] = [
            {
                "field": "stage",
                "operator": "equals",
                "value": "NEW",
            }
        ]
        payload["actions"] = [
            {
                "type": "CREATE_FOLLOW_UP",
                "config": {
                    "days_after": 1,
                    "title": "Contact new property lead",
                    "follow_up_type": "CALL",
                    "description": "Contact the lead about the property.",
                },
            }
        ]

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client, payload)

            response = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == AutomationRule.STATUS_ACTIVE
