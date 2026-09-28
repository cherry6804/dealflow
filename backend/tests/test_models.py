from app.db.models.organization import Organization
from app.db.models.user import User


def test_user_model_fields() -> None:
    user = User(
        email="user@example.com",
        display_name="Test User",
    )

    assert user.id is None
    assert user.email == "user@example.com"
    assert user.display_name == "Test User"
    assert user.is_active is None


def test_organization_model_fields() -> None:
    organization = Organization(
        name="Test Organization",
    )

    assert organization.id is None
    assert organization.name == "Test Organization"
    assert organization.is_active is None


def test_user_model_defaults_are_configured() -> None:
    assert User.__table__.c.id.default is not None
    assert User.__table__.c.is_active.default is not None


def test_organization_model_defaults_are_configured() -> None:
    assert Organization.__table__.c.id.default is not None
    assert Organization.__table__.c.is_active.default is not None