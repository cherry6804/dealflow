import uuid

from app.db.models.contact import Contact


def test_contact_model_has_expected_table_name() -> None:
    assert Contact.__tablename__ == "contacts"


def test_contact_model_has_expected_columns() -> None:
    columns = Contact.__table__.columns

    assert set(columns.keys()) == {
        "id",
        "organization_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "is_active",
        "created_at",
        "updated_at",
    }


def test_contact_model_uses_uuid_primary_key() -> None:
    column = Contact.__table__.c.id

    assert column.primary_key is True
    assert column.default is not None


def test_contact_model_is_tenant_scoped() -> None:
    column = Contact.__table__.c.organization_id

    assert column.nullable is False
    assert column.index is True
    assert len(column.foreign_keys) == 1

    foreign_key = next(iter(column.foreign_keys))

    assert foreign_key.target_fullname == "organizations.id"


def test_contact_model_identity_and_communication_fields() -> None:
    columns = Contact.__table__.columns

    assert columns.first_name.nullable is False
    assert columns.last_name.nullable is True
    assert columns.email.nullable is True
    assert columns.phone.nullable is True


def test_contact_model_lifecycle_field() -> None:
    column = Contact.__table__.c.is_active

    assert column.nullable is False
    assert column.default is not None
    assert column.default.arg is True


def test_contact_model_timestamps() -> None:
    columns = Contact.__table__.columns

    assert columns.created_at.nullable is False
    assert columns.created_at.server_default is not None

    assert columns.updated_at.nullable is False
    assert columns.updated_at.server_default is not None
    assert columns.updated_at.onupdate is not None


def test_contact_model_can_be_constructed() -> None:
    organization_id = uuid.uuid4()
    contact_id = uuid.uuid4()

    contact = Contact(
        id=contact_id,
        organization_id=organization_id,
        first_name="Test",
        last_name="Contact",
        email="test@example.com",
        phone="+911234567890",
        is_active=True,
    )

    assert contact.id == contact_id
    assert isinstance(contact.id, uuid.UUID)
    assert contact.organization_id == organization_id
    assert contact.first_name == "Test"
    assert contact.last_name == "Contact"
    assert contact.email == "test@example.com"
    assert contact.phone == "+911234567890"
    assert contact.is_active is True