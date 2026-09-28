import uuid

from app.auth.password import hash_password
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import SessionLocal


def create_test_user() -> User:
    """Create a user with a valid password hash for database tests."""
    return User(
        email=f"membership-{uuid.uuid4()}@example.com",
        display_name="Membership User",
        password_hash=hash_password("TestPassword!123"),
    )


def create_test_organization() -> Organization:
    """Create an organization for database tests."""
    return Organization(
        name=f"Membership Organization {uuid.uuid4()}",
    )


def test_membership_can_be_created() -> None:
    with SessionLocal() as session:
        user = create_test_user()
        organization = create_test_organization()

        membership = Membership(
            user=user,
            organization=organization,
        )

        session.add(membership)
        session.commit()

        assert membership.id is not None
        assert membership.user_id == user.id
        assert membership.organization_id == organization.id
        assert membership.is_active is True


def test_membership_relationships_work() -> None:
    with SessionLocal() as session:
        user = User(
            email=f"relationship-{uuid.uuid4()}@example.com",
            display_name="Relationship User",
            password_hash=hash_password("TestPassword!123"),
        )
        organization = Organization(
            name=f"Relationship Organization {uuid.uuid4()}",
        )

        membership = Membership(
            user=user,
            organization=organization,
        )

        session.add(membership)
        session.commit()

        session.refresh(user)
        session.refresh(organization)

        assert user.memberships == [membership]
        assert organization.memberships == [membership]


def test_duplicate_user_organization_membership_is_rejected() -> None:
    with SessionLocal() as session:
        user = User(
            email=f"duplicate-{uuid.uuid4()}@example.com",
            display_name="Duplicate User",
            password_hash=hash_password("TestPassword!123"),
        )
        organization = Organization(
            name=f"Duplicate Organization {uuid.uuid4()}",
        )

        first_membership = Membership(
            user=user,
            organization=organization,
        )

        session.add(first_membership)
        session.commit()

        second_membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
        )

        session.add(second_membership)

        try:
            session.commit()
        except Exception:
            session.rollback()
        else:
            raise AssertionError(
                "Duplicate user-organization membership should be rejected."
            )