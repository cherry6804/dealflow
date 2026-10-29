"""Integration tests for tenant-scoped automation rules and execution audits."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.automation_rules import router as automation_rules_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.organization import Organization
from app.db.models.plan import Plan
from app.db.models.plan_entitlement import PlanEntitlement
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session
from tests.test_deals_api import (
    create_authorized_user as _create_authorized_user,
)

TestingSessionLocal = SessionLocal

AUTOMATION_READ = "automation.read"
AUTOMATION_CREATE = "automation.create"
AUTOMATION_UPDATE = "automation.update"

WORKFLOW_AUTOMATION_ENTITLEMENT = "workflow_automation"

ALL_PERMISSIONS = (
    AUTOMATION_READ,
    AUTOMATION_CREATE,
    AUTOMATION_UPDATE,
)


def create_authorized_user(
    db: Session,
    *,
    permission_keys: tuple[str, ...],
) -> tuple[User, Organization]:
    """Create an authorized test user with an eligible automation plan."""
    user, organization = _create_authorized_user(
        db,
        permission_keys=permission_keys,
    )

    plan = Plan(
        # Must fit the plans.code VARCHAR(40) database column.
        code=f"auto-{organization.id.hex}",
        name="Automation Test Plan",
        monthly_price_paise=49900,
        currency="INR",
        included_seats=2,
        is_active=True,
    )
    db.add(plan)
    db.flush()

    subscription = Subscription(
        organization_id=organization.id,
        plan_id=plan.id,
        plan_code=plan.code,
        status=Subscription.STATUS_ACTIVE,
        billing_interval="MONTHLY",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )

    entitlement = PlanEntitlement(
        plan_id=plan.id,
        key=WORKFLOW_AUTOMATION_ENTITLEMENT,
        value_type="BOOLEAN",
        value=True,
    )

    db.add_all([subscription, entitlement])
    db.commit()

    return user, organization


def create_test_app(*, user: User) -> FastAPI:
    """Create a test application with the automation router."""
    app = FastAPI()
    app.include_router(automation_rules_router)

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )
    return app


def valid_payload() -> dict[str, object]:
    """Return a valid automation-rule creation request."""
    return {
        "name": "Follow up on new deals",
        "description": "Create a follow-up when a deal is created.",
        "trigger_type": "DEAL_CREATED",
        "trigger_config": {"source": "deals"},
        "conditions": [
            {"field": "stage", "operator": "equals", "value": "NEW"}
        ],
        "actions": [
            {"type": "CREATE_FOLLOW_UP", "config": {"days_after": 1}}
        ],
    }


def request_as(
    *,
    user: User,
    organization: Organization,
) -> TestClient:
    """Return a test client configured for one organization."""
    app = create_test_app(user=user)
    client = TestClient(app)
    client.headers.update({"X-Organization-ID": str(organization.id)})
    return client


def create_rule(
    client: TestClient,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a rule and return its response."""
    response = client.post(
        "/api/v1/automation-rules",
        json=payload if payload is not None else valid_payload(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def set_workflow_automation_entitlement(
    db: Session,
    *,
    organization: Organization,
    enabled: bool | None,
) -> None:
    """Enable, disable, or remove this organization's automation entitlement."""
    subscription = db.scalar(
        select(Subscription)
        .where(Subscription.organization_id == organization.id)
        .order_by(Subscription.created_at.desc(), Subscription.id.desc())
    )
    assert subscription is not None
    assert subscription.plan_id is not None

    entitlement = db.scalar(
        select(PlanEntitlement).where(
            PlanEntitlement.plan_id == subscription.plan_id,
            PlanEntitlement.key == WORKFLOW_AUTOMATION_ENTITLEMENT,
        )
    )

    if enabled is None:
        if entitlement is not None:
            db.delete(entitlement)
    elif entitlement is not None:
        entitlement.value = enabled
    else:
        db.add(
            PlanEntitlement(
                plan_id=subscription.plan_id,
                key=WORKFLOW_AUTOMATION_ENTITLEMENT,
                value_type="BOOLEAN",
                value=enabled,
            )
        )

    db.commit()


def test_create_automation_rule_successfully() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.post(
                "/api/v1/automation-rules",
                json=valid_payload(),
            )

        assert response.status_code == 201, response.text
        result = response.json()

        assert result["organization_id"] == str(organization.id)
        assert result["name"] == "Follow up on new deals"
        assert result["trigger_type"] == "DEAL_CREATED"
        assert result["status"] == AutomationRule.STATUS_DRAFT
        assert result["created_by_user_id"] == str(user.id)
        assert result["conditions"] == valid_payload()["conditions"]
        assert result["actions"] == valid_payload()["actions"]

        persisted = db.scalar(
            select(AutomationRule).where(
                AutomationRule.id == UUID(result["id"])
            )
        )
        assert persisted is not None
        assert persisted.organization_id == organization.id
        assert persisted.status == AutomationRule.STATUS_DRAFT


def test_create_automation_rule_rejects_blank_name() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        payload = valid_payload()
        payload["name"] = "   "

        with request_as(user=user, organization=organization) as client:
            response = client.post("/api/v1/automation-rules", json=payload)

        assert response.status_code == 422, response.text


def test_create_automation_rule_requires_create_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(AUTOMATION_READ,),
        )

        with request_as(user=user, organization=organization) as client:
            response = client.post(
                "/api/v1/automation-rules",
                json=valid_payload(),
            )

        assert response.status_code == 403, response.text


def test_create_automation_rule_rejects_disabled_entitlement() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        set_workflow_automation_entitlement(
            db,
            organization=organization,
            enabled=False,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.post(
                "/api/v1/automation-rules",
                json=valid_payload(),
            )

        assert response.status_code == 403, response.text


def test_create_automation_rule_rejects_missing_entitlement() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        set_workflow_automation_entitlement(
            db,
            organization=organization,
            enabled=None,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.post(
                "/api/v1/automation-rules",
                json=valid_payload(),
            )

        assert response.status_code == 403, response.text


def test_list_automation_rules_filters_and_paginates() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            for name in ("Rule One", "Rule Two", "Rule Three"):
                payload = valid_payload()
                payload["name"] = name
                response = client.post(
                    "/api/v1/automation-rules",
                    json=payload,
                )
                assert response.status_code == 201, response.text

            response = client.get(
                "/api/v1/automation-rules",
                params={"page": 1, "page_size": 2},
            )
            draft_response = client.get(
                "/api/v1/automation-rules",
                params={"status": "DRAFT"},
            )

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 3
        assert len(result["items"]) == 2
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert result["total_pages"] == 2

        assert draft_response.status_code == 200, draft_response.text
        assert draft_response.json()["total"] == 3


def test_list_automation_rules_rejects_invalid_status() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.get(
                "/api/v1/automation-rules",
                params={"status": "INVALID"},
            )

        assert response.status_code == 422, response.text


def test_list_automation_rules_requires_read_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(AUTOMATION_CREATE,),
        )

        with request_as(user=user, organization=organization) as client:
            response = client.get("/api/v1/automation-rules")

        assert response.status_code == 403, response.text


def test_get_automation_rule_successfully() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)
            response = client.get(
                f"/api/v1/automation-rules/{created['id']}"
            )

        assert response.status_code == 200, response.text
        assert response.json()["id"] == created["id"]


def test_get_automation_rule_rejects_another_tenant() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user_b, organization=organization_b) as client_b:
            created = create_rule(client_b)

        with request_as(user=user_a, organization=organization_a) as client_a:
            response = client_a.get(
                f"/api/v1/automation-rules/{created['id']}"
            )

        assert response.status_code == 404, response.text


def test_update_draft_automation_rule_successfully() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)
            response = client.patch(
                f"/api/v1/automation-rules/{created['id']}",
                json={"name": "Updated automation rule"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Updated automation rule"
        assert response.json()["status"] == AutomationRule.STATUS_DRAFT
        assert response.json()["updated_by_user_id"] == str(user.id)


def test_update_active_automation_rule_is_rejected() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)

            activation = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )
            assert activation.status_code == 200, activation.text

            response = client.patch(
                f"/api/v1/automation-rules/{created['id']}",
                json={"name": "Changed while active"},
            )

        assert response.status_code == 409, response.text


def test_activate_automation_rule_requires_an_action() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        payload = valid_payload()
        payload["actions"] = []

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client, payload)
            response = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )

        assert response.status_code == 409, response.text
        assert "action" in response.json()["detail"].lower()


def test_activate_and_disable_automation_rule() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)

            activation = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )
            assert activation.status_code == 200, activation.text
            assert activation.json()["status"] == AutomationRule.STATUS_ACTIVE

            disabling = client.post(
                f"/api/v1/automation-rules/{created['id']}/disable"
            )

        assert disabling.status_code == 200, disabling.text
        assert disabling.json()["status"] == AutomationRule.STATUS_DISABLED

        db.expire_all()
        persisted = db.get(AutomationRule, UUID(created["id"]))
        assert persisted is not None
        assert persisted.status == AutomationRule.STATUS_DISABLED


def test_update_automation_rule_requires_update_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(AUTOMATION_READ, AUTOMATION_CREATE),
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)
            response = client.patch(
                f"/api/v1/automation-rules/{created['id']}",
                json={"name": "Unauthorized update"},
            )

        assert response.status_code == 403, response.text


def test_activate_automation_rule_requires_update_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(AUTOMATION_READ, AUTOMATION_CREATE),
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)
            response = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )

        assert response.status_code == 403, response.text


def test_activate_automation_rule_rejects_disabled_entitlement() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)

            set_workflow_automation_entitlement(
                db,
                organization=organization,
                enabled=False,
            )

            response = client.post(
                f"/api/v1/automation-rules/{created['id']}/activate"
            )

        assert response.status_code == 403, response.text


def test_update_automation_rule_rejects_another_tenant() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user_b, organization=organization_b) as client_b:
            created = create_rule(client_b)

        with request_as(user=user_a, organization=organization_a) as client_a:
            response = client_a.patch(
                f"/api/v1/automation-rules/{created['id']}",
                json={"name": "Cross-tenant modification"},
            )

        assert response.status_code == 404, response.text

        db.expire_all()
        persisted = db.get(AutomationRule, UUID(created["id"]))
        assert persisted is not None
        assert persisted.name == "Follow up on new deals"


def test_list_automation_executions_returns_audit_details() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            created = create_rule(client)
            rule_id = UUID(created["id"])

            execution = AutomationExecution(
                organization_id=organization.id,
                rule_id=rule_id,
                event_type="DEAL_CREATED",
                event_id=UUID(int=1001),
                status=AutomationExecution.STATUS_FAILED,
                action_results=[
                    {
                        "action_type": "CREATE_FOLLOW_UP",
                        "status": "FAILED",
                        "reason": "Test failure",
                    }
                ],
                error_message="One or more automation actions failed.",
            )
            db.add(execution)
            db.commit()
            execution_id = execution.id

            response = client.get(
                "/api/v1/automation-rules/executions",
                params={
                    "status": "FAILED",
                    "rule_id": str(rule_id),
                },
            )

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["page_size"] == 20
        assert result["total_pages"] == 1

        item = result["items"][0]
        assert item["id"] == str(execution_id)
        assert item["organization_id"] == str(organization.id)
        assert item["rule_id"] == str(rule_id)
        assert item["event_type"] == "DEAL_CREATED"
        assert item["status"] == "FAILED"
        assert item["error_message"] == (
            "One or more automation actions failed."
        )
        assert item["action_results"][0]["reason"] == "Test failure"
        assert item["created_at"] is not None


def test_list_automation_executions_rejects_invalid_status() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.get(
                "/api/v1/automation-rules/executions",
                params={"status": "INVALID"},
            )

        assert response.status_code == 422, response.text


def test_list_automation_executions_requires_read_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(AUTOMATION_CREATE,),
        )

        with request_as(user=user, organization=organization) as client:
            response = client.get("/api/v1/automation-rules/executions")

        assert response.status_code == 403, response.text


def test_list_automation_executions_is_tenant_scoped() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_as(user=user_b, organization=organization_b) as client_b:
            created = create_rule(client_b)
            rule_id = UUID(created["id"])

            execution = AutomationExecution(
                organization_id=organization_b.id,
                rule_id=rule_id,
                event_type="DEAL_CREATED",
                event_id=UUID(int=1002),
                status=AutomationExecution.STATUS_SUCCEEDED,
                action_results=[],
            )
            db.add(execution)
            db.commit()

        with request_as(user=user_a, organization=organization_a) as client_a:
            response = client_a.get(
                "/api/v1/automation-rules/executions"
            )

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 0
        assert result["items"] == []

def request_with_sibvo_access(
    *,
    user: User,
    organization: Organization,
    sibvo_access: dict | None,
) -> TestClient:
    """Return a client whose session was issued through SIBVO SSO."""
    app = create_test_app(user=user)
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user=user,
        session_organization_id=organization.id,
        sibvo_attested=True,
        sibvo_access=sibvo_access,
    )
    client = TestClient(app)
    client.headers.update({"X-Organization-ID": str(organization.id)})
    return client


def sibvo_snapshot(*, enabled: bool) -> dict:
    return {
        "subscription_status": "active",
        "plan_version_id": None,
        "product_role": "owner",
        "entitlements": [
            {
                "feature_key": WORKFLOW_AUTOMATION_ENTITLEMENT,
                "enabled": enabled,
                "limit_value": None,
                "limit_unit": None,
            }
        ],
    }


def test_sibvo_entitlement_allows_without_local_subscription() -> None:
    """SSO sessions never need Dealsflo's legacy subscription rows."""
    with TestingSessionLocal() as db:
        user, organization = _create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )
        db.commit()

        with request_with_sibvo_access(
            user=user,
            organization=organization,
            sibvo_access=sibvo_snapshot(enabled=True),
        ) as client:
            response = client.post("/api/v1/automation-rules", json=valid_payload())

        assert response.status_code == 201, response.text


def test_sibvo_entitlement_overrides_local_plan() -> None:
    """A locally enabled plan cannot grant a feature SIBVO has disabled."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=ALL_PERMISSIONS,
        )

        with request_with_sibvo_access(
            user=user,
            organization=organization,
            sibvo_access=sibvo_snapshot(enabled=False),
        ) as client:
            disabled = client.post("/api/v1/automation-rules", json=valid_payload())

        with request_with_sibvo_access(
            user=user,
            organization=organization,
            sibvo_access={**sibvo_snapshot(enabled=True), "entitlements": []},
        ) as client:
            missing = client.post("/api/v1/automation-rules", json=valid_payload())

        with request_with_sibvo_access(
            user=user,
            organization=organization,
            sibvo_access=None,
        ) as client:
            no_snapshot = client.post("/api/v1/automation-rules", json=valid_payload())

        assert disabled.status_code == 403
        assert missing.status_code == 403
        assert no_snapshot.status_code == 403
