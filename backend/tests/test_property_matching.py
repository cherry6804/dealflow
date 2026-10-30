
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import (
    CustomerRequirementLocation,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.property import Property
from app.properties.matching_service import get_matching_properties
from app.db.session import SessionLocal

from tests.test_customer_requirements_api import (
    create_customer_requirement,
    create_organization,
)
from app.properties.matching_service import get_property_match_results

def test_matching_returns_property_matching_all_criteria() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.budget_min = Decimal("10000000.00")
        requirement.budget_max = Decimal("15000000.00")
        requirement.budget_currency = "INR"

        db.add(
            CustomerRequirementLocation(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                city="Chennai",
                locality="Anna Nagar",
                is_active=True,
            )
        )
        db.add(
            CustomerRequirementPropertyPreference(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                property_type="APARTMENT",
                bhk_min=2,
                bhk_max=3,
                is_active=True,
            )
        )

        matching_property = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("12500000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=3,
        )
        db.add(matching_property)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert [item.id for item in matches] == [matching_property.id]


def test_matching_excludes_unavailable_properties() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        reserved_property = Property(
            organization_id=organization.id,
            status=Property.STATUS_RESERVED,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("12500000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=3,
        )
        db.add(reserved_property)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert reserved_property.id not in {item.id for item in matches}


def test_matching_rejects_inactive_requirement() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.is_active = False
        db.flush()

        with pytest.raises(
            ValueError,
            match="Active customer requirement not found",
        ):
            get_matching_properties(
                db,
                organization_id=organization.id,
                requirement_id=requirement.id,
            )


def test_matching_rejects_cross_tenant_requirement() -> None:
    with SessionLocal() as db:
        organization_a = create_organization(db)
        organization_b = create_organization(db)
        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )
        db.flush()

        with pytest.raises(
            ValueError,
            match="Active customer requirement not found",
        ):
            get_matching_properties(
                db,
                organization_id=organization_a.id,
                requirement_id=requirement_b.id,
            )


def test_matching_rejects_budget_currency_mismatch() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.budget_min = Decimal("100000.00")
        requirement.budget_max = Decimal("200000.00")
        requirement.budget_currency = "INR"

        property_record = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("150000.00"),
            currency="USD",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=2,
        )
        db.add(property_record)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert property_record.id not in {item.id for item in matches}

def test_matching_excludes_property_in_wrong_location() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        db.add(
            CustomerRequirementLocation(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                city="Chennai",
                locality="Anna Nagar",
                is_active=True,
            )
        )

        property_record = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("12500000.00"),
            currency="INR",
            city="Chennai",
            locality="Velachery",
            property_type="APARTMENT",
            bhk=3,
        )
        db.add(property_record)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert property_record.id not in {
            item.id for item in matches
        }


def test_matching_excludes_property_with_wrong_property_type() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        db.add(
            CustomerRequirementPropertyPreference(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                property_type="APARTMENT",
                bhk_min=2,
                bhk_max=3,
                is_active=True,
            )
        )

        property_record = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("12500000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="VILLA",
            bhk=3,
        )
        db.add(property_record)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert property_record.id not in {
            item.id for item in matches
        }

def test_matching_includes_property_at_budget_boundaries() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.budget_min = Decimal("10000000.00")
        requirement.budget_max = Decimal("15000000.00")
        requirement.budget_currency = "INR"

        property_record = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("10000000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=2,
        )
        db.add(property_record)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert property_record.id in {item.id for item in matches}


def test_matching_ignores_inactive_property_preferences() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        db.add(
            CustomerRequirementPropertyPreference(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                property_type="APARTMENT",
                bhk_min=2,
                bhk_max=3,
                is_active=False,
            )
        )

        property_record = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("12500000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="VILLA",
            bhk=3,
        )
        db.add(property_record)
        db.flush()

        matches = get_matching_properties(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert property_record.id in {item.id for item in matches}

def test_match_results_explain_matching_and_mismatching_criteria() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        requirement.budget_min = Decimal("10000000.00")
        requirement.budget_max = Decimal("15000000.00")
        requirement.budget_currency = "INR"

        db.add(
            CustomerRequirementLocation(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                city="Chennai",
                locality="Anna Nagar",
                is_active=True,
            )
        )
        db.add(
            CustomerRequirementPropertyPreference(
                organization_id=organization.id,
                customer_requirement_id=requirement.id,
                property_type="APARTMENT",
                bhk_min=2,
                bhk_max=3,
                is_active=True,
            )
        )

        matching_property = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("12500000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=3,
        )
        mismatching_property = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("20000000.00"),
            currency="INR",
            city="Chennai",
            locality="Anna Nagar",
            property_type="APARTMENT",
            bhk=3,
        )
        db.add_all([matching_property, mismatching_property])
        db.flush()

        results = get_property_match_results(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        results_by_id = {
            result.property.id: result
            for result in results
        }

        matching_result = results_by_id[matching_property.id]
        assert matching_result.overall_match is True
        assert {
            criterion.criterion: criterion.status
            for criterion in matching_result.criteria
        } == {
            "LOCATION": "MATCH",
            "PROPERTY_TYPE_AND_BHK": "MATCH",
            "BUDGET": "MATCH",
        }

        mismatching_result = results_by_id[mismatching_property.id]
        assert mismatching_result.overall_match is False
        assert {
            criterion.criterion: criterion.status
            for criterion in mismatching_result.criteria
        } == {
            "LOCATION": "MATCH",
            "PROPERTY_TYPE_AND_BHK": "MATCH",
            "BUDGET": "MISMATCH",
        }

        assert all(
            criterion.explanation.strip()
            for result in results
            for criterion in result.criteria
        )


def test_match_results_mark_unconfigured_criteria() -> None:
    with SessionLocal() as db:
        organization = create_organization(db)
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        property_record = Property(
            organization_id=organization.id,
            status=Property.STATUS_AVAILABLE,
            transaction_type=Property.TRANSACTION_TYPE_SALE,
            price=Decimal("5000000.00"),
            currency="INR",
            city="Chennai",
            locality="Velachery",
            property_type="VILLA",
            bhk=2,
        )
        db.add(property_record)
        db.flush()

        results = get_property_match_results(
            db,
            organization_id=organization.id,
            requirement_id=requirement.id,
        )

        assert len(results) == 1
        assert results[0].overall_match is True
        assert {
            criterion.criterion: criterion.status
            for criterion in results[0].criteria
        } == {
            "LOCATION": "NOT_CONFIGURED",
            "PROPERTY_TYPE_AND_BHK": "NOT_CONFIGURED",
            "BUDGET": "NOT_CONFIGURED",
        }


def test_match_results_reject_cross_tenant_requirement() -> None:
    with SessionLocal() as db:
        organization_a = create_organization(db)
        organization_b = create_organization(db)
        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )
        db.flush()

        with pytest.raises(
            ValueError,
            match="Active customer requirement not found",
        ):
            get_property_match_results(
                db,
                organization_id=organization_a.id,
                requirement_id=requirement_b.id,
            )