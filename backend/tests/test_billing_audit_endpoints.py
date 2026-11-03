"""DFR1-053: billing reconciliation records are read through the real HTTP endpoints, with real authorization.

The existing ``test_billing_audit_api.py`` calls the handler functions with mocks. These tests send HTTP requests
through ``TestClient`` and use the real database. Only tenant resolution is overridden, so the real permission check
(``enforce_permission`` on the membership's roles) still runs.

Dealsflo has no endpoint that receives or replays a billing webhook. Billing events reach the reconciliation service
only from code, and the service is called here directly to create records. Endpoint-level replay is therefore not
tested. See the evidence document, section 12.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.billing_audit import router as billing_audit_router
from app.billing.reconciliation_service import reconcile_webhook_event
from app.db.models.billing_reconciliation_record import BillingReconciliationRecord
from app.db.models.billing_webhook_event import BillingWebhookEvent
from app.db.models.membership import Membership
from app.db.models.subscription import Subscription
from app.db.session import SessionLocal, get_db_session
from app.tenant.dependencies import TenantContext, get_tenant_context
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

LIST_URL = "/api/v1/billing/audit/reconciliations"


def _app(tenant: TenantContext | None) -> FastAPI:
    app = FastAPI()
    app.include_router(billing_audit_router)

    def override_session() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_session
    if tenant is not None:
        app.dependency_overrides[get_tenant_context] = lambda: tenant
    return app


def _tenant_for(user, organization) -> TenantContext:
    with SessionLocal() as db:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == organization.id,
            )
        )
        assert membership is not None
        db.expunge(membership)
    return TenantContext(organization=organization, membership=membership)


@pytest.fixture
def cleanup() -> Iterator[list[uuid.UUID]]:
    created: list[uuid.UUID] = []
    yield created
    with SessionLocal() as db:
        for organization_id in created:
            db.execute(delete(BillingReconciliationRecord).where(
                BillingReconciliationRecord.organization_id == organization_id))
            db.execute(delete(Subscription).where(Subscription.organization_id == organization_id))
        db.commit()


def _record_for(organization_id: uuid.UUID, *, provider_subscription_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a subscription and a webhook event for it, then reconcile the event. Returns (record id, event id)."""
    with SessionLocal() as db:
        subscription = Subscription(
            organization_id=organization_id,
            plan_code="pro",
            status="ACTIVE",
            billing_interval="MONTHLY",
            provider="stripe",
            provider_subscription_id=provider_subscription_id,
        )
        db.add(subscription)
        event = BillingWebhookEvent(
            provider="stripe",
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_type="invoice.paid",
            payload={"data": {"subscription": provider_subscription_id}},
            status="RECEIVED",
            attempt_count=0,
        )
        db.add(event)
        db.flush()
        result = reconcile_webhook_event(db, webhook_event_id=event.id)
        db.commit()
        return result.record.id, event.id


def test_unauthenticated_requests_are_refused(cleanup) -> None:
    client = TestClient(_app(None))
    response = client.get(LIST_URL)
    assert response.status_code in (401, 403)


def test_a_member_without_the_audit_permission_is_refused(cleanup) -> None:
    user, organization = create_manager(permissions=("deals.read",))
    cleanup.append(organization.id)
    client = TestClient(_app(_tenant_for(user, organization)))

    assert client.get(LIST_URL).status_code == 403
    assert client.get(f"{LIST_URL}/{uuid.uuid4()}").status_code == 403


def test_the_list_shows_only_the_callers_organization(cleanup) -> None:
    owner_a, org_a = create_owner_manager(permissions=("billing.audit.read",))
    _owner_b, org_b = create_owner_manager(permissions=("billing.audit.read",))
    cleanup.extend([org_a.id, org_b.id])
    own, _own_event = _record_for(org_a.id, provider_subscription_id=f"sub_{uuid.uuid4().hex}")
    other, _other_event = _record_for(org_b.id, provider_subscription_id=f"sub_{uuid.uuid4().hex}")

    client = TestClient(_app(_tenant_for(owner_a, org_a)))
    listed = client.get(LIST_URL)

    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert str(own) in ids
    assert str(other) not in ids


def test_another_organizations_record_is_not_found_through_the_detail_endpoint(cleanup) -> None:
    owner_a, org_a = create_owner_manager(permissions=("billing.audit.read",))
    _owner_b, org_b = create_owner_manager(permissions=("billing.audit.read",))
    cleanup.extend([org_a.id, org_b.id])
    other, _event = _record_for(org_b.id, provider_subscription_id=f"sub_{uuid.uuid4().hex}")

    client = TestClient(_app(_tenant_for(owner_a, org_a)))
    response = client.get(f"{LIST_URL}/{other}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Billing reconciliation record not found."


def test_a_repeated_reconciliation_is_visible_once_through_the_list(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("billing.audit.read",))
    cleanup.append(organization.id)
    first, event_id = _record_for(organization.id, provider_subscription_id=f"sub_{uuid.uuid4().hex}")

    # Reconcile the same webhook event again. The service returns the existing record and writes nothing new.
    with SessionLocal() as db:
        again = reconcile_webhook_event(db, webhook_event_id=event_id)
        db.commit()
        assert again.created is False
        assert again.record.id == first

    client = TestClient(_app(_tenant_for(owner, organization)))
    listed = client.get(LIST_URL).json()["items"]
    assert [item["id"] for item in listed] == [str(first)]


def test_an_event_that_does_not_exist_writes_no_record(cleanup) -> None:
    owner, organization = create_owner_manager(permissions=("billing.audit.read",))
    cleanup.append(organization.id)

    with SessionLocal() as db:
        with pytest.raises(ValueError, match="not found"):
            reconcile_webhook_event(db, webhook_event_id=uuid.uuid4())
        db.rollback()

    client = TestClient(_app(_tenant_for(owner, organization)))
    assert client.get(LIST_URL).json()["items"] == []
