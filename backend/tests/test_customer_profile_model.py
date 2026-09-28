import uuid

from app.db.models.customer_profile import CustomerProfile


def test_customer_profile_model_has_expected_table_name() -> None:
    assert CustomerProfile.__tablename__ == "customer_profiles"


def test_customer_profile_model_has_expected_columns() -> None:
    columns = CustomerProfile.__table__.columns

    assert set(columns.keys()) == {
        "id",
        "organization_id",
        "contact_id",
        "is_active",
        "customer_notes",
        "created_at",
        "updated_at",
    }


def test_customer_profile_model_uses_uuid_primary_key() -> None:
    column = CustomerProfile.__table__.c.id

    assert column.primary_key is True
    assert column.default is not None


def test_customer_profile_model_is_tenant_scoped() -> None:
    column = CustomerProfile.__table__.c.organization_id

    assert column.nullable is False
    assert column.index is True
    assert len(column.foreign_keys) == 1

    foreign_key = next(iter(column.foreign_keys))

    assert foreign_key.target_fullname == "organizations.id"


def test_customer_profile_model_requires_contact() -> None:
    column = CustomerProfile.__table__.c.contact_id

    assert column.nullable is False
    assert column.unique is True
    assert column.index is True
    assert len(column.foreign_keys) == 1

    foreign_key = next(iter(column.foreign_keys))

    assert foreign_key.target_fullname == "contacts.id"


def test_customer_profile_model_lifecycle_field() -> None:
    column = CustomerProfile.__table__.c.is_active

    assert column.nullable is False
    assert column.default is not None
    assert column.default.arg is True


def test_customer_profile_model_business_context_field() -> None:
    column = CustomerProfile.__table__.c.customer_notes

    assert column.nullable is True


def test_customer_profile_model_timestamps() -> None:
    columns = CustomerProfile.__table__.columns

    assert columns.created_at.nullable is False
    assert columns.created_at.server_default is not None

    assert columns.updated_at.nullable is False
    assert columns.updated_at.server_default is not None
    assert columns.updated_at.onupdate is not None


def test_customer_profile_model_can_be_constructed() -> None:
    organization_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    customer_profile_id = uuid.uuid4()

    customer_profile = CustomerProfile(
        id=customer_profile_id,
        organization_id=organization_id,
        contact_id=contact_id,
        is_active=True,
        customer_notes="Interested in residential property.",
    )

    assert customer_profile.id == customer_profile_id
    assert isinstance(customer_profile.id, uuid.UUID)
    assert customer_profile.organization_id == organization_id
    assert customer_profile.contact_id == contact_id
    assert customer_profile.is_active is True
    assert (
        customer_profile.customer_notes
        == "Interested in residential property."
    )