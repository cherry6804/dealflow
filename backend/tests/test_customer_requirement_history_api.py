from __future__ import annotations

from sqlalchemy import select

from app.db.models.customer_requirement_history import (
    CustomerRequirementHistory,
)

from tests.test_customer_requirements_api import (
    TestingSessionLocal,
    add_tenant_header,
    create_authorized_user,
    make_test_client,
)


def test_create_customer_requirement_creates_initial_history() -> None:
    """DF-56: Creating a requirement creates its initial version-1 history."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.create",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 201

        requirement_id = response.json()["id"]

        history_records = list(
            db.scalars(
                select(CustomerRequirementHistory).where(
                    CustomerRequirementHistory.customer_requirement_id
                    == requirement_id,
                    CustomerRequirementHistory.organization_id
                    == organization.id,
                )
            ).all()
        )

        assert len(history_records) == 1

        history = history_records[0]

        assert history.customer_requirement_id is not None
        assert str(history.customer_requirement_id) == requirement_id
        assert history.organization_id == organization.id
        assert history.version == 1
        assert history.actor_id == user.id
        assert history.change_type == "REQUIREMENT_CREATED"

        assert history.snapshot["requirement"]["id"] == requirement_id
        assert (
            history.snapshot["requirement"]["organization_id"]
            == str(organization.id)
        )

        assert history.snapshot["requirement"]["budget_min"] is None
        assert history.snapshot["requirement"]["budget_max"] is None
        assert history.snapshot["requirement"]["budget_currency"] is None

        assert history.snapshot["requirement"]["lead_id"] is None
        assert history.snapshot["requirement"]["customer_profile_id"] is None

        assert history.snapshot["locations"] == []
        assert history.snapshot["property_preferences"] == []
        assert history.snapshot["possession_parking_preference"] is None


def test_create_customer_requirement_history_is_tenant_scoped() -> None:
    """DF-56: Initial history belongs to the requirement's tenant."""

    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_key="requirements.create",
        )

        user_b, organization_b = create_authorized_user(
            db,
            permission_key="requirements.create",
        )

        with make_test_client(user=user_a) as client:
            add_tenant_header(client, organization_a)

            response_a = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response_a.status_code == 201

        requirement_a_id = response_a.json()["id"]

        with make_test_client(user=user_b) as client:
            add_tenant_header(client, organization_b)

            response_b = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response_b.status_code == 201

        requirement_b_id = response_b.json()["id"]

        history_a = list(
            db.scalars(
                select(CustomerRequirementHistory).where(
                    CustomerRequirementHistory.customer_requirement_id
                    == requirement_a_id,
                    CustomerRequirementHistory.organization_id
                    == organization_a.id,
                )
            ).all()
        )

        history_b = list(
            db.scalars(
                select(CustomerRequirementHistory).where(
                    CustomerRequirementHistory.customer_requirement_id
                    == requirement_b_id,
                    CustomerRequirementHistory.organization_id
                    == organization_b.id,
                )
            ).all()
        )

        assert len(history_a) == 1
        assert len(history_b) == 1

        assert history_a[0].version == 1
        assert history_b[0].version == 1

        assert history_a[0].organization_id == organization_a.id
        assert history_b[0].organization_id == organization_b.id

        assert history_a[0].actor_id == user_a.id
        assert history_b[0].actor_id == user_b.id

        assert history_a[0].customer_requirement_id != history_b[0].customer_requirement_id