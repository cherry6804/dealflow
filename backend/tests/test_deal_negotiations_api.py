
"""Integration tests for deal negotiation state and history."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deals import router as deals_router
from app.api.deal_negotiations import router as negotiations_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.deal import Deal
from app.db.models.deal_negotiation import (
    DealNegotiation,
    DealNegotiationHistory,
)
from app.db.models.property import Property
from app.db.models.customer_profile import CustomerProfile
from app.db.session import SessionLocal, get_db_session

from tests.test_deals_api import (
    create_authorized_user,
    create_customer_profile,
    create_property,
    valid_payload,
)

TestingSessionLocal = SessionLocal


def create_test_app(*, user) -> FastAPI:
    app = FastAPI()
    app.include_router(deals_router)
    app.include_router(negotiations_router)

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


def create_deal_for_test(
    client: TestClient,
    db: Session,
    organization_id,
) -> UUID:
    customer = create_customer_profile(
        db,
        organization=db.get(
            __import__(
                "app.db.models.organization",
                fromlist=["Organization"],
            ).Organization,
            organization_id,
        ),
    )
    property_record = create_property(
        db,
        organization=db.get(
            __import__(
                "app.db.models.organization",
                fromlist=["Organization"],
            ).Organization,
            organization_id,
        ),
    )
    db.commit()

    response = client.post(
        "/api/v1/deals",
        json=valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
        ),
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def test_create_negotiation_and_initial_history() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            response = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={
                    "state": "IN_PROGRESS",
                    "note": "Initial negotiation started.",
                },
            )

            assert response.status_code == 201, response.text
            assert response.json()["state"] == "IN_PROGRESS"
            assert response.json()["deal_id"] == deal_id

            history_response = client.get(
                f"/api/v1/deals/{deal_id}/negotiation/history"
            )

        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["total"] == 1
        assert history["items"][0]["from_state"] is None
        assert history["items"][0]["to_state"] == "IN_PROGRESS"
        assert history["items"][0]["note"] == "Initial negotiation started."


def test_update_negotiation_records_history() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            updated = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={
                    "state": "WAITING_ON_CUSTOMER",
                    "note": "Customer reviewing the offer.",
                },
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["state"] == "WAITING_ON_CUSTOMER"

            history_response = client.get(
                f"/api/v1/deals/{deal_id}/negotiation/history"
            )

        assert history_response.status_code == 200
        history = history_response.json()
        assert history["total"] == 2
        assert history["items"][0]["to_state"] == "IN_PROGRESS"
        assert history["items"][1]["from_state"] == "IN_PROGRESS"
        assert history["items"][1]["to_state"] == "WAITING_ON_CUSTOMER"
        assert history["items"][1]["note"] == "Customer reviewing the offer."

        persisted = db.scalar(
            select(DealNegotiation).where(
                DealNegotiation.deal_id == UUID(deal_id),
                DealNegotiation.organization_id == organization.id,
            )
        )
        assert persisted is not None
        assert persisted.state == "WAITING_ON_CUSTOMER"


def test_duplicate_negotiation_creation_returns_conflict() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            deal_id = deal_response.json()["id"]

            first = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            second = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "STALLED"},
            )

        assert first.status_code == 201, first.text
        assert second.status_code == 409, second.text


def test_repeated_state_update_returns_conflict() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            response = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )

        assert response.status_code == 409, response.text


def test_negotiation_is_hidden_from_another_organization() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer_b = create_customer_profile(db, organization=organization_b)
        property_b = create_property(db, organization=organization_b)
        db.commit()

        app_b = create_test_app(user=user_b)
        with TestClient(app_b) as client_b:
            client_b.headers.update(
                {"X-Organization-ID": str(organization_b.id)}
            )
            deal_response = client_b.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer_b.id,
                    property_id=property_b.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            create_response = client_b.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert create_response.status_code == 201, create_response.text

        app_a = create_test_app(user=user_a)
        with TestClient(app_a) as client_a:
            client_a.headers.update(
                {"X-Organization-ID": str(organization_a.id)}
            )
            response = client_a.get(
                f"/api/v1/deals/{deal_id}/negotiation"
            )

        assert response.status_code == 404, response.text


def test_negotiation_read_requires_read_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read"),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            response = client.get(
                f"/api/v1/deals/{deal_id}/negotiation"
            )

        assert response.status_code == 403, response.text


def test_invalid_negotiation_transition_returns_conflict() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            response = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "COMPLETED"},
            )

        assert response.status_code == 409, response.text


def test_cancelling_negotiation_requires_reason() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            response = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "CANCELLED"},
            )

        assert response.status_code == 409, response.text


def test_cancelling_negotiation_records_reason_in_history() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            updated = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={
                    "state": "CANCELLED",
                    "note": "Buyer withdrew from negotiations.",
                },
            )
            assert updated.status_code == 200, updated.text

            history_response = client.get(
                f"/api/v1/deals/{deal_id}/negotiation/history"
            )

        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["total"] == 2
        latest = history["items"][-1]
        assert latest["from_state"] == "IN_PROGRESS"
        assert latest["to_state"] == "CANCELLED"
        assert latest["note"] == "Buyer withdrew from negotiations."


def test_reopening_cancelled_negotiation_requires_reason() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            cancelled = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={
                    "state": "CANCELLED",
                    "note": "Buyer initially withdrew.",
                },
            )
            assert cancelled.status_code == 200, cancelled.text

            response = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )

        assert response.status_code == 409, response.text


def test_reopening_cancelled_negotiation_with_reason_succeeds() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deal_negotiations.read",
                "deal_negotiations.update",
            ),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            deal_response = client.post(
                "/api/v1/deals",
                json=valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                ),
            )
            assert deal_response.status_code == 201, deal_response.text
            deal_id = deal_response.json()["id"]

            created = client.post(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={"state": "IN_PROGRESS"},
            )
            assert created.status_code == 201, created.text

            cancelled = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={
                    "state": "CANCELLED",
                    "note": "Buyer initially withdrew.",
                },
            )
            assert cancelled.status_code == 200, cancelled.text

            reopened = client.patch(
                f"/api/v1/deals/{deal_id}/negotiation",
                json={
                    "state": "IN_PROGRESS",
                    "note": "Buyer returned with a revised offer.",
                },
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["state"] == "IN_PROGRESS"

            history_response = client.get(
                f"/api/v1/deals/{deal_id}/negotiation/history"
            )

        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["total"] == 3
        reopening = history["items"][-1]
        assert reopening["from_state"] == "CANCELLED"
        assert reopening["to_state"] == "IN_PROGRESS"
        assert reopening["note"] == "Buyer returned with a revised offer."
