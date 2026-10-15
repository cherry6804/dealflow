"""API tests for the customer requirement property matching endpoint."""

from app.db.models.customer_requirement_location import (
    CustomerRequirementLocation,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.session import SessionLocal

from tests.test_customer_requirements_api import (
    add_tenant_header,
    create_authorized_user,
    create_customer_requirement,
    create_organization,
    create_user,
    make_test_client,
)


BASE_URL = "/api/v1/customer-requirements"


def test_matching_endpoint_returns_empty_list_when_no_properties_match() -> None:
    with SessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"{BASE_URL}/{requirement.id}/matches"
            )

        assert response.status_code == 200
        assert response.json() == []


def test_matching_endpoint_returns_404_for_cross_tenant_requirement() -> None:
    with SessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        organization_b = create_organization(db)
        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.get(
                f"{BASE_URL}/{requirement_b.id}/matches"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Active customer requirement not found."
        )


def test_matching_endpoint_requires_read_permission() -> None:
    with SessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"{BASE_URL}/{requirement.id}/matches"
            )

        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Organization access denied."
        )


def test_matching_endpoint_requires_tenant_context() -> None:
    with SessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            response = client.get(
                f"{BASE_URL}/{requirement.id}/matches"
            )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Organization context is required."
        )


def test_matching_endpoint_returns_404_for_inactive_requirement() -> None:
    with SessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.is_active = False
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"{BASE_URL}/{requirement.id}/matches"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Active customer requirement not found."
        )


def test_matching_endpoint_rejects_invalid_requirement_id() -> None:
    with SessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"{BASE_URL}/not-a-uuid/matches"
            )

        assert response.status_code == 422
