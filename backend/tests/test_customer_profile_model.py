from __future__ import annotations

import uuid

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.orm import configure_mappers

from app.db.models.customer_profile import CustomerProfile


def test_customer_profile_model_has_expected_table_name() -> None:
    assert CustomerProfile.__tablename__ == "customer_profiles"


def test_customer_profile_model_has_primary_key() -> None:
    column = CustomerProfile.__table__.c.id

    assert column.primary_key is True
    assert column.nullable is False


def test_customer_profile_model_is_tenant_scoped() -> None:
    column = CustomerProfile.__table__.c.organization_id

    assert column.nullable is False
    assert column.index is True

    organization_foreign_keys = {
        foreign_key
        for foreign_key in column.foreign_keys
        if foreign_key.target_fullname == "organizations.id"
    }

    assert len(organization_foreign_keys) == 1


def test_customer_profile_model_has_tenant_safe_contact_foreign_key() -> None:
    constraints = [
        constraint
        for constraint in CustomerProfile.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_customer_profiles_contact_tenant"
    ]

    assert len(constraints) == 1

    constraint = constraints[0]

    assert [column.name for column in constraint.columns] == [
        "contact_id",
        "organization_id",
    ]

    assert [element.target_fullname for element in constraint.elements] == [
        "contacts.id",
        "contacts.organization_id",
    ]

    assert constraint.ondelete == "CASCADE"


def test_customer_profile_model_has_contact_relationship() -> None:
    relationship = CustomerProfile.__mapper__.relationships["contact"]

    assert relationship.uselist is False
    assert relationship.back_populates == "customer_profile"


def test_customer_profile_model_has_organization_relationship() -> None:
    relationship = CustomerProfile.__mapper__.relationships["organization"]

    assert relationship.uselist is False
    assert relationship.back_populates == "customer_profiles"


def test_customer_profile_model_contact_id_is_unique() -> None:
    column = CustomerProfile.__table__.c.contact_id

    assert column.nullable is False
    assert column.unique is True
    assert column.index is True


def test_customer_profile_model_has_lifecycle_field() -> None:
    column = CustomerProfile.__table__.c.is_active

    assert column.nullable is False
    assert column.default is not None


def test_customer_profile_model_has_timestamps() -> None:
    created_at = CustomerProfile.__table__.c.created_at
    updated_at = CustomerProfile.__table__.c.updated_at

    assert created_at.nullable is False
    assert updated_at.nullable is False
    assert created_at.server_default is not None
    assert updated_at.server_default is not None


def test_customer_profile_model_can_be_constructed() -> None:
    customer_profile = CustomerProfile(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        is_active=True,
        customer_notes="Interested in residential property.",
    )

    assert customer_profile.id is not None
    assert customer_profile.organization_id is not None
    assert customer_profile.contact_id is not None
    assert customer_profile.is_active is True
    assert customer_profile.customer_notes == (
        "Interested in residential property."
    )


def test_customer_profile_model_mappers_configure_successfully() -> None:
    configure_mappers()