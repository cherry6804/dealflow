
"""Integration tests for tenant-scoped payment milestones."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.payment_milestones import router as payment_milestones_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.deal import Deal
from app.db.models.payment_milestone import PaymentMilestone
from app.db.session import SessionLocal, get_db_session

from tests.test_deals_api import (
    _create_test_deal,
    create_authorized_user,
)
TestingSessionLocal = SessionLocal


def create_payment_test_app(*, user) -> FastAPI:
    """Create a test app with the payment-milestone router."""
    app = FastAPI()
    app.include_router(payment_milestones_router)

    def override_get_db_session():
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


def create_payment_test_deal(
    db: Session,
    *,
    user,
    organization,
) -> Deal:
    """Create a deal belonging to the test organization."""
    deal = _create_test_deal(
        db,
        user=user,
        organization=organization,
    )
    return deal


def payment_payload(
    *,
    due_at: datetime | None = None,
) -> dict[str, object]:
    """Return a valid payment-milestone request."""
    return {
        "name": "Booking advance",
        "amount": "250000.00",
        "currency": "INR",
        "due_at": (
            due_at or datetime.now(timezone.utc) + timedelta(days=7)
        ).isoformat(),
        "notes": "Initial payment for the property booking.",
    }


def test_create_and_list_payment_milestones() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.read",
            ),
        )
        deal = create_payment_test_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id
        db.commit()

        app = create_payment_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            create_response = client.post(
                f"/api/v1/deals/{deal_id}/payment-milestones",
                json=payment_payload(),
            )
            assert create_response.status_code == 201, create_response.text

            created = create_response.json()
            assert created["organization_id"] == str(organization.id)
            assert created["deal_id"] == str(deal_id)
            assert created["name"] == "Booking advance"
            assert created["amount"] == "250000.00"
            assert created["currency"] == "INR"
            assert created["status"] == "PENDING"
            assert created["paid_at"] is None
            assert created["is_overdue"] is False

            list_response = client.get(
                f"/api/v1/deals/{deal_id}/payment-milestones"
            )

        assert list_response.status_code == 200, list_response.text
        result = list_response.json()
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == created["id"]

        persisted = db.get(PaymentMilestone, UUID(created["id"]))
        assert persisted is not None
        assert persisted.created_by_user_id == user.id
        assert persisted.status == PaymentMilestone.STATUS_PENDING


def test_mark_payment_milestone_paid_records_actor_and_reference() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.update",
                "payment_milestones.read",
            ),
        )
        deal = create_payment_test_deal(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        app = create_payment_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            create_response = client.post(
                f"/api/v1/deals/{deal.id}/payment-milestones",
                json=payment_payload(),
            )
            assert create_response.status_code == 201, create_response.text
            milestone_id = create_response.json()["id"]

            paid_response = client.post(
                f"/api/v1/payment-milestones/{milestone_id}/mark-paid",
                json={"payment_reference": "BANK-TRANSFER-123"},
            )

        assert paid_response.status_code == 200, paid_response.text
        result = paid_response.json()
        assert result["status"] == "PAID"
        assert result["paid_at"] is not None
        assert result["paid_by_user_id"] == str(user.id)
        assert result["payment_reference"] == "BANK-TRANSFER-123"
        assert result["is_overdue"] is False

        db.expire_all()
        persisted = db.get(PaymentMilestone, UUID(milestone_id))
        assert persisted is not None
        assert persisted.status == PaymentMilestone.STATUS_PAID
        assert persisted.paid_by_user_id == user.id
        assert persisted.paid_at is not None


def test_cannot_mark_already_paid_milestone_paid_again() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.update",
            ),
        )
        deal = create_payment_test_deal(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        app = create_payment_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            create_response = client.post(
                f"/api/v1/deals/{deal.id}/payment-milestones",
                json=payment_payload(),
            )
            assert create_response.status_code == 201, create_response.text
            milestone_id = create_response.json()["id"]

            first = client.post(
                f"/api/v1/payment-milestones/{milestone_id}/mark-paid",
                json={"payment_reference": "REF-1"},
            )
            second = client.post(
                f"/api/v1/payment-milestones/{milestone_id}/mark-paid",
                json={"payment_reference": "REF-2"},
            )

        assert first.status_code == 200, first.text
        assert second.status_code == 409, second.text

        db.expire_all()
        persisted = db.get(PaymentMilestone, UUID(milestone_id))
        assert persisted is not None
        assert persisted.payment_reference == "REF-1"


def test_payment_milestone_is_isolated_between_organizations() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.read",
                "payment_milestones.update",
            ),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.read",
                "payment_milestones.update",
            ),
        )
        deal_b = create_payment_test_deal(
            db,
            user=user_b,
            organization=organization_b,
        )
        db.commit()

        app_b = create_payment_test_app(user=user_b)
        with TestClient(app_b) as client_b:
            client_b.headers.update(
                {"X-Organization-ID": str(organization_b.id)}
            )
            created = client_b.post(
                f"/api/v1/deals/{deal_b.id}/payment-milestones",
                json=payment_payload(),
            )
        assert created.status_code == 201, created.text
        milestone_id = created.json()["id"]

        app_a = create_payment_test_app(user=user_a)
        with TestClient(app_a) as client_a:
            client_a.headers.update(
                {"X-Organization-ID": str(organization_a.id)}
            )
            get_response = client_a.get(
                f"/api/v1/payment-milestones/{milestone_id}"
            )
            update_response = client_a.patch(
                f"/api/v1/payment-milestones/{milestone_id}",
                json={"name": "Unauthorized edit"},
            )
            paid_response = client_a.post(
                f"/api/v1/payment-milestones/{milestone_id}/mark-paid",
                json={},
            )

        assert get_response.status_code == 404
        assert update_response.status_code == 404
        assert paid_response.status_code == 404


def test_create_payment_milestone_requires_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read",),
        )
        deal = create_payment_test_deal(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        app = create_payment_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post(
                f"/api/v1/deals/{deal.id}/payment-milestones",
                json=payment_payload(),
            )

        assert response.status_code == 403, response.text


def test_create_payment_milestone_rejects_nonpositive_amount() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("payment_milestones.create",),
        )
        deal = create_payment_test_deal(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        payload = payment_payload()
        payload["amount"] = "0"

        app = create_payment_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post(
                f"/api/v1/deals/{deal.id}/payment-milestones",
                json=payload,
            )

        assert response.status_code == 422, response.text


def test_update_and_cancel_pending_milestone() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.update",
            ),
        )
        deal = create_payment_test_deal(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        app = create_payment_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            create_response = client.post(
                f"/api/v1/deals/{deal.id}/payment-milestones",
                json=payment_payload(),
            )
            assert create_response.status_code == 201, create_response.text
            milestone_id = create_response.json()["id"]

            update_response = client.patch(
                f"/api/v1/payment-milestones/{milestone_id}",
                json={"name": "Updated booking advance"},
            )
            assert update_response.status_code == 200, update_response.text
            assert update_response.json()["name"] == "Updated booking advance"

            cancel_response = client.post(
                f"/api/v1/payment-milestones/{milestone_id}/cancel"
            )

        assert cancel_response.status_code == 200, cancel_response.text
        assert cancel_response.json()["status"] == "CANCELLED"
        assert cancel_response.json()["is_overdue"] is False


def test_list_milestones_rejects_another_organizations_deal() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=("payment_milestones.read",),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=(
                "payment_milestones.create",
                "payment_milestones.read",
            ),
        )
        deal_b = create_payment_test_deal(
            db,
            user=user_b,
            organization=organization_b,
        )
        db.commit()

        app_a = create_payment_test_app(user=user_a)
        with TestClient(app_a) as client_a:
            client_a.headers.update(
                {"X-Organization-ID": str(organization_a.id)}
            )
            response = client_a.get(
                f"/api/v1/deals/{deal_b.id}/payment-milestones"
            )

        assert response.status_code == 404, response.text
