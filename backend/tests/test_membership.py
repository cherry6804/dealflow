import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Membership, Organization, User
from app.db.session import SessionLocal


def test_membership_can_be_created() -> None:
    with SessionLocal() as session:
        user = User(
            email=f"membership-{uuid.uuid4()}@example.com",
            display_name="Membership User",
        )
        organization = Organization(
            name=f"Membership Organization {uuid.uuid4()}",
        )

        membership = Membership(
            user=user,
            organization=organization,
        )

        session.add(membership)
        session.commit()
        session.refresh(membership)

        assert membership.id is not None
        assert membership.user_id == user.id
        assert membership.organization_id == organization.id
        assert membership.is_active is True

        session.delete(membership)
        session.delete(user)
        session.delete(organization)
        session.commit()


def test_membership_relationships_work() -> None:
    with SessionLocal() as session:
        user = User(
            email=f"relationship-{uuid.uuid4()}@example.com",
            display_name="Relationship User",
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
        session.refresh(membership)

        assert membership.user is user
        assert membership.organization is organization
        assert membership in user.memberships
        assert membership in organization.memberships

        session.delete(membership)
        session.delete(user)
        session.delete(organization)
        session.commit()


def test_duplicate_user_organization_membership_is_rejected() -> None:
    with SessionLocal() as session:
        user = User(
            email=f"duplicate-{uuid.uuid4()}@example.com",
            display_name="Duplicate User",
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

        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()

        session.delete(first_membership)
        session.delete(user)
        session.delete(organization)
        session.commit()