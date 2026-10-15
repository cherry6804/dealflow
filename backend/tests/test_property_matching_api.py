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
from decimal import Decimal

from app.db.models.property import Property

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

def test_match_results_endpoint_returns_explanations() -> None:
    with SessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.budget_min = Decimal("1000000.00")
        requirement.budget_max = Decimal("2000000.00")
        requirement.budget_currency = "INR"

        matching_property = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("1500000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=2,
        )
        mismatching_property = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("3000000.00"),
            currency="INR",
            city="Chennai",
            locality="Velachery",
            property_type="VILLA",
            bhk=3,
        )
        db.add_all([matching_property, mismatching_property])
        db.commit()
        db.refresh(matching_property)
        db.refresh(mismatching_property)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"{BASE_URL}/{requirement.id}/match-results"
            )

        assert response.status_code == 200
        body = response.json()

        assert body["requirement_id"] == str(requirement.id)
        assert body["total"] == 2
        assert body["total"] == 2

        results_by_id = {
            item["property"]["id"]: item
            for item in body["items"]
        }

        matching_result = results_by_id[str(matching_property.id)]
        assert matching_result["overall_match"] is True
        assert {
            item["criterion"]: item["status"]
            for item in matching_result["criteria"]
        } == {
            "LOCATION": "NOT_CONFIGURED",
            "PROPERTY_TYPE_AND_BHK": "NOT_CONFIGURED",
            "BUDGET": "MATCH",
        }

        mismatching_result = results_by_id[str(mismatching_property.id)]
        assert mismatching_result["overall_match"] is False
        assert {
            item["criterion"]: item["status"]
            for item in mismatching_result["criteria"]
        } == {
            "LOCATION": "NOT_CONFIGURED",
            "PROPERTY_TYPE_AND_BHK": "NOT_CONFIGURED",
            "BUDGET": "MISMATCH",
        }

        assert all(
            item["explanation"].strip()
            for result in body["items"]
            for item in result["criteria"]
        )


def test_match_results_endpoint_rejects_cross_tenant_requirement() -> None:
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
                f"{BASE_URL}/{requirement_b.id}/match-results"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Active customer requirement not found."
        )


def test_match_results_endpoint_requires_read_permission() -> None:
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
                f"{BASE_URL}/{requirement.id}/match-results"
            )

        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Organization access denied."
        )