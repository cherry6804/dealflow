
"""Integration tests for tenant-scoped deal commissions."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deal_commissions import router as deal_commissions_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.deal_commission import DealCommission
from app.db.session import SessionLocal, get_db_session
from tests.test_deals_api import (
    _create_test_deal,
    create_authorized_user,
)

TestingSessionLocal = SessionLocal


def create_commission_test_app(*, user) -> FastAPI:
    """Create a test app with the deal-commission router."""
    app = FastAPI()
    app.include_router(deal_commissions_router)

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


def commission_payload(
    *,
    commission_type: str = "FIXED",
    fixed_amount: str | None = "50000.00",
    rate_percent: str | None = None,
) -> dict[str, object]:
    """Return a valid commission request payload."""
    return {
        "commission_type": commission_type,
        "fixed_amount": fixed_amount,
        "rate_percent": rate_percent,
        "currency": "INR",
        "terms": "Commission payable according to the agreed terms.",
    }


def create_commission(
    client: TestClient,
    deal_id: UUID,
    payload: dict[str, object] | None = None,
) -> dict:
    """Create a commission and assert that the API succeeds."""
    response = client.post(
        f"/api/v1/deals/{deal_id}/commissions",
        json=payload or commission_payload(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_fixed_commissions() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.read"),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )

            created = create_commission(client, deal_id)

            assert created["organization_id"] == str(organization.id)
            assert created["deal_id"] == str(deal_id)
            assert created["commission_type"] == "FIXED"
            assert created["fixed_amount"] == "50000.00"
            assert created["rate_percent"] is None
            assert created["currency"] == "INR"
            assert created["status"] == "PROPOSED"
            assert created["calculated_amount"] == "50000.00"
            assert created["agreed_at"] is None
            assert created["paid_at"] is None

            list_response = client.get(
                f"/api/v1/deals/{deal_id}/commissions"
            )

        assert list_response.status_code == 200, list_response.text
        result = list_response.json()
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == created["id"]

        persisted = db.get(DealCommission, UUID(created["id"]))
        assert persisted is not None
        assert persisted.created_by_user_id == user.id
        assert persisted.status == DealCommission.STATUS_PROPOSED


def test_percentage_commission_calculates_from_deal_expected_value() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create",),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        payload = commission_payload(
            commission_type="PERCENTAGE",
            fixed_amount=None,
            rate_percent="2.0000",
        )

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post(
                f"/api/v1/deals/{deal_id}/commissions",
                json=payload,
            )

        assert response.status_code == 201, response.text
        result = response.json()
        assert result["commission_type"] == "PERCENTAGE"
        assert result["fixed_amount"] is None
        assert result["rate_percent"] == "2.0000"
        assert result["calculated_amount"] == "150000.00"


def test_percentage_commission_without_deal_value_returns_null_amount() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create",),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal.expected_value = None
        deal_id = deal.id
        db.commit()

        payload = commission_payload(
            commission_type="PERCENTAGE",
            fixed_amount=None,
            rate_percent="2.0000",
        )

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post(
                f"/api/v1/deals/{deal_id}/commissions",
                json=payload,
            )

        assert response.status_code == 201, response.text
        assert response.json()["calculated_amount"] is None


def test_create_commission_rejects_invalid_values() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create",),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        invalid_payloads = [
            {
                "commission_type": "FIXED",
                "fixed_amount": "0",
                "rate_percent": None,
                "currency": "INR",
            },
            {
                "commission_type": "PERCENTAGE",
                "fixed_amount": None,
                "rate_percent": "0",
                "currency": "INR",
            },
            {
                "commission_type": "PERCENTAGE",
                "fixed_amount": "50000.00",
                "rate_percent": "2",
                "currency": "INR",
            },
            {
                "commission_type": "FIXED",
                "fixed_amount": "50000.00",
                "rate_percent": "2",
                "currency": "INR",
            },
            {
                "commission_type": "PERCENTAGE",
                "fixed_amount": None,
                "rate_percent": "101",
                "currency": "INR",
            },
            {
                "commission_type": "UNKNOWN",
                "fixed_amount": "50000.00",
                "rate_percent": None,
                "currency": "INR",
            },
        ]

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )

            for payload in invalid_payloads:
                response = client.post(
                    f"/api/v1/deals/{deal_id}/commissions",
                    json=payload,
                )
                assert response.status_code == 422, (
                    f"Expected 422 for {payload}; "
                    f"got {response.status_code}: {response.text}"
                )


def test_agree_and_mark_commission_paid() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.update"),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )

            created = create_commission(client, deal_id)
            commission_id = created["id"]

            agree_response = client.post(
                f"/api/v1/commissions/{commission_id}/agree"
            )
            assert agree_response.status_code == 200, agree_response.text
            agreed = agree_response.json()
            assert agreed["status"] == "AGREED"
            assert agreed["agreed_at"] is not None

            paid_response = client.post(
                f"/api/v1/commissions/{commission_id}/mark-paid",
                json={"payment_reference": "BANK-TRANSFER-123"},
            )
            assert paid_response.status_code == 200, paid_response.text

        paid = paid_response.json()
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None
        assert paid["payment_reference"] == "BANK-TRANSFER-123"
        assert paid["calculated_amount"] == "50000.00"

        db.expire_all()
        persisted = db.get(DealCommission, UUID(commission_id))
        assert persisted is not None
        assert persisted.status == DealCommission.STATUS_PAID
        assert persisted.payment_reference == "BANK-TRANSFER-123"
        assert persisted.paid_at is not None


def test_cannot_mark_proposed_commission_paid() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.update"),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            created = create_commission(client, deal_id)

            response = client.post(
                f"/api/v1/commissions/{created['id']}/mark-paid",
                json={},
            )

        assert response.status_code == 409, response.text

        db.expire_all()
        persisted = db.get(DealCommission, UUID(created["id"]))
        assert persisted is not None
        assert persisted.status == DealCommission.STATUS_PROPOSED
        assert persisted.paid_at is None


def test_cannot_agree_or_pay_commission_twice() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.update"),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            created = create_commission(client, deal_id)
            commission_id = created["id"]

            first_agree = client.post(
                f"/api/v1/commissions/{commission_id}/agree"
            )
            second_agree = client.post(
                f"/api/v1/commissions/{commission_id}/agree"
            )
            first_paid = client.post(
                f"/api/v1/commissions/{commission_id}/mark-paid",
                json={"payment_reference": "REF-1"},
            )
            second_paid = client.post(
                f"/api/v1/commissions/{commission_id}/mark-paid",
                json={"payment_reference": "REF-2"},
            )

        assert first_agree.status_code == 200, first_agree.text
        assert second_agree.status_code == 409, second_agree.text
        assert first_paid.status_code == 200, first_paid.text
        assert second_paid.status_code == 409, second_paid.text

        db.expire_all()
        persisted = db.get(DealCommission, UUID(commission_id))
        assert persisted is not None
        assert persisted.payment_reference == "REF-1"


def test_update_agreed_commission_requires_reagreement() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.update"),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            created = create_commission(client, deal_id)
            commission_id = created["id"]

            agree_response = client.post(
                f"/api/v1/commissions/{commission_id}/agree"
            )
            assert agree_response.status_code == 200, agree_response.text

            update_response = client.patch(
                f"/api/v1/commissions/{commission_id}",
                json={"fixed_amount": "60000.00"},
            )

        assert update_response.status_code == 200, update_response.text
        updated = update_response.json()
        assert updated["fixed_amount"] == "60000.00"
        assert updated["status"] == "PROPOSED"
        assert updated["agreed_at"] is None
        assert updated["calculated_amount"] == "60000.00"


def test_cancelled_commission_cannot_be_agreed() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.update"),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            created = create_commission(client, deal_id)
            commission_id = created["id"]

            cancel_response = client.post(
                f"/api/v1/commissions/{commission_id}/cancel"
            )
            assert cancel_response.status_code == 200, cancel_response.text
            assert cancel_response.json()["status"] == "CANCELLED"

            agree_response = client.post(
                f"/api/v1/commissions/{commission_id}/agree"
            )

        assert agree_response.status_code == 409, agree_response.text


def test_commission_is_isolated_between_organizations() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=(
                "commission.create",
                "commission.read",
                "commission.update",
            ),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=(
                "commission.create",
                "commission.read",
                "commission.update",
            ),
        )
        deal_b = _create_test_deal(
            db, user=user_b, organization=organization_b
        )
        deal_b_id = deal_b.id
        db.commit()

        app_b = create_commission_test_app(user=user_b)
        with TestClient(app_b) as client_b:
            client_b.headers.update(
                {"X-Organization-ID": str(organization_b.id)}
            )
            created = create_commission(client_b, deal_b_id)

        commission_id = created["id"]

        app_a = create_commission_test_app(user=user_a)
        with TestClient(app_a) as client_a:
            client_a.headers.update(
                {"X-Organization-ID": str(organization_a.id)}
            )
            get_response = client_a.get(
                f"/api/v1/commissions/{commission_id}"
            )
            update_response = client_a.patch(
                f"/api/v1/commissions/{commission_id}",
                json={"terms": "Unauthorized edit"},
            )
            agree_response = client_a.post(
                f"/api/v1/commissions/{commission_id}/agree"
            )

        assert get_response.status_code == 404
        assert update_response.status_code == 404
        assert agree_response.status_code == 404


def test_create_commission_requires_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read",),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post(
                f"/api/v1/deals/{deal_id}/commissions",
                json=commission_payload(),
            )

        assert response.status_code == 403, response.text


def test_list_commissions_requires_read_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("commission.create",),
        )
        deal = _create_test_deal(
            db, user=user, organization=organization
        )
        deal_id = deal.id
        db.commit()

        app = create_commission_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.get(
                f"/api/v1/deals/{deal_id}/commissions"
            )

        assert response.status_code == 403, response.text


def test_list_commissions_rejects_another_organizations_deal() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=("commission.read",),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=("commission.create", "commission.read"),
        )
        deal_b = _create_test_deal(
            db, user=user_b, organization=organization_b
        )
        deal_b_id = deal_b.id
        db.commit()

        app = create_commission_test_app(user=user_a)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_a.id)}
            )
            response = client.get(
                f"/api/v1/deals/{deal_b_id}/commissions"
            )

        assert response.status_code == 404, response.text
