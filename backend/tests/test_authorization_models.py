import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
def database() -> Generator[None, None, None]:
    """Create a clean database for every authorization-model test."""
    Base.metadata.create_all(engine)

    try:
        yield
    finally:
        Base.metadata.drop_all(engine)


def create_user(session: Session) -> User:
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4()}@example.com",
        display_name="Authorization Test User",
        password_hash="test-password-hash",
        is_active=True,
    )

    session.add(user)
    session.flush()

    return user


def create_organization(session: Session) -> Organization:
    """Create a test organization."""
    organization = Organization(
        id=uuid.uuid4(),
        name=f"Authorization Organization {uuid.uuid4()}",
        is_active=True,
    )

    session.add(organization)
    session.flush()

    return organization


def create_membership(
    session: Session,
    user: User,
    organization: Organization,
) -> Membership:
    """Create an organization membership."""
    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=organization.id,
        is_active=True,
    )

    session.add(membership)
    session.flush()

    return membership


def create_role(
    session: Session,
    name: str | None = None,
) -> Role:
    """Create an authorization role."""
    role = Role(
        id=uuid.uuid4(),
        name=name or f"Role-{uuid.uuid4()}",
        description="Authorization test role",
        is_active=True,
    )

    session.add(role)
    session.flush()

    return role


def create_permission(
    session: Session,
    key: str | None = None,
) -> Permission:
    """Create an authorization permission."""
    permission = Permission(
        id=uuid.uuid4(),
        key=key or f"resource.action.{uuid.uuid4()}",
        description="Authorization test permission",
        is_active=True,
    )

    session.add(permission)
    session.flush()

    return permission


def test_permission_creation() -> None:
    """A permission can be created and persisted."""
    with TestingSessionLocal() as session:
        permission = create_permission(
            session,
            key="contacts.read",
        )

        session.commit()

        stored_permission = session.get(Permission, permission.id)

        assert stored_permission is not None
        assert stored_permission.key == "contacts.read"
        assert stored_permission.description == "Authorization test permission"
        assert stored_permission.is_active is True


def test_role_creation() -> None:
    """A role can be created and persisted."""
    with TestingSessionLocal() as session:
        role = create_role(
            session,
            name="Manager",
        )

        session.commit()

        stored_role = session.get(Role, role.id)

        assert stored_role is not None
        assert stored_role.name == "Manager"
        assert stored_role.description == "Authorization test role"
        assert stored_role.is_active is True


def test_role_permission_relationship() -> None:
    """A role can be associated with a permission."""
    with TestingSessionLocal() as session:
        role = create_role(
            session,
            name="Manager",
        )
        permission = create_permission(
            session,
            key="contacts.read",
        )

        role_permission = RolePermission(
            role=role,
            permission=permission,
        )

        session.add(role_permission)
        session.commit()

        session.refresh(role)
        session.refresh(permission)

        assert len(role.role_permissions) == 1
        assert role.role_permissions[0].permission_id == permission.id

        assert len(permission.role_permissions) == 1
        assert permission.role_permissions[0].role_id == role.id


def test_membership_role_relationship() -> None:
    """A role can be assigned to an organization membership."""
    with TestingSessionLocal() as session:
        user = create_user(session)
        organization = create_organization(session)
        membership = create_membership(
            session,
            user,
            organization,
        )
        role = create_role(
            session,
            name="Agent",
        )

        membership_role = MembershipRole(
            membership=membership,
            role=role,
        )

        session.add(membership_role)
        session.commit()

        session.refresh(membership)
        session.refresh(role)

        assert len(membership.membership_roles) == 1
        assert membership.membership_roles[0].role_id == role.id

        assert len(role.membership_roles) == 1
        assert role.membership_roles[0].membership_id == membership.id


def test_membership_can_have_multiple_roles() -> None:
    """A membership can have multiple authorization roles."""
    with TestingSessionLocal() as session:
        user = create_user(session)
        organization = create_organization(session)
        membership = create_membership(
            session,
            user,
            organization,
        )

        manager_role = create_role(
            session,
            name="Manager",
        )
        agent_role = create_role(
            session,
            name="Agent",
        )

        session.add_all(
            [
                MembershipRole(
                    membership=membership,
                    role=manager_role,
                ),
                MembershipRole(
                    membership=membership,
                    role=agent_role,
                ),
            ]
        )

        session.commit()

        session.refresh(membership)

        role_ids = {
            membership_role.role_id
            for membership_role in membership.membership_roles
        }

        assert role_ids == {
            manager_role.id,
            agent_role.id,
        }


def test_role_can_have_multiple_permissions() -> None:
    """A role can contain multiple permissions."""
    with TestingSessionLocal() as session:
        role = create_role(
            session,
            name="Manager",
        )

        contacts_read = create_permission(
            session,
            key="contacts.read",
        )
        contacts_update = create_permission(
            session,
            key="contacts.update",
        )
        leads_read = create_permission(
            session,
            key="leads.read",
        )

        session.add_all(
            [
                RolePermission(
                    role=role,
                    permission=contacts_read,
                ),
                RolePermission(
                    role=role,
                    permission=contacts_update,
                ),
                RolePermission(
                    role=role,
                    permission=leads_read,
                ),
            ]
        )

        session.commit()

        session.refresh(role)

        permission_ids = {
            role_permission.permission_id
            for role_permission in role.role_permissions
        }

        assert permission_ids == {
            contacts_read.id,
            contacts_update.id,
            leads_read.id,
        }


def test_duplicate_permission_key_is_rejected() -> None:
    """Permission keys must be globally unique."""
    with TestingSessionLocal() as session:
        create_permission(
            session,
            key="contacts.read",
        )
        session.commit()

        duplicate_permission = Permission(
            id=uuid.uuid4(),
            key="contacts.read",
            description="Duplicate permission",
            is_active=True,
        )

        session.add(duplicate_permission)

        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_role_name_is_rejected() -> None:
    """Role names must be globally unique."""
    with TestingSessionLocal() as session:
        create_role(
            session,
            name="Manager",
        )
        session.commit()

        duplicate_role = Role(
            id=uuid.uuid4(),
            name="Manager",
            description="Duplicate role",
            is_active=True,
        )

        session.add(duplicate_role)

        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_role_permission_is_rejected() -> None:
    """A role cannot receive the same permission more than once."""
    with TestingSessionLocal() as session:
        role = create_role(
            session,
            name="Manager",
        )
        permission = create_permission(
            session,
            key="contacts.read",
        )

        session.add(
            RolePermission(
                role=role,
                permission=permission,
            )
        )
        session.commit()

        duplicate = RolePermission(
            role_id=role.id,
            permission_id=permission.id,
        )

        session.add(duplicate)

        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_membership_role_is_rejected() -> None:
    """A membership cannot receive the same role more than once."""
    with TestingSessionLocal() as session:
        user = create_user(session)
        organization = create_organization(session)
        membership = create_membership(
            session,
            user,
            organization,
        )
        role = create_role(
            session,
            name="Manager",
        )

        session.add(
            MembershipRole(
                membership=membership,
                role=role,
            )
        )
        session.commit()

        duplicate = MembershipRole(
            membership_id=membership.id,
            role_id=role.id,
        )

        session.add(duplicate)

        with pytest.raises(IntegrityError):
            session.commit()


def test_role_permission_cascade_delete() -> None:
    """Deleting a role removes its role-permission assignments."""
    with TestingSessionLocal() as session:
        role = create_role(
            session,
            name="Manager",
        )
        permission = create_permission(
            session,
            key="contacts.read",
        )

        role_permission = RolePermission(
            role=role,
            permission=permission,
        )

        session.add(role_permission)
        session.commit()

        role_permission_id = role_permission.id
        role_id = role.id

        session.delete(role)
        session.commit()

        assert session.get(Role, role_id) is None
        assert session.get(RolePermission, role_permission_id) is None
        assert session.get(Permission, permission.id) is not None


def test_membership_role_cascade_delete() -> None:
    """Deleting a membership removes its role assignments."""
    with TestingSessionLocal() as session:
        user = create_user(session)
        organization = create_organization(session)
        membership = create_membership(
            session,
            user,
            organization,
        )
        role = create_role(
            session,
            name="Manager",
        )

        membership_role = MembershipRole(
            membership=membership,
            role=role,
        )

        session.add(membership_role)
        session.commit()

        membership_role_id = membership_role.id
        membership_id = membership.id

        session.delete(membership)
        session.commit()

        assert session.get(Membership, membership_id) is None
        assert session.get(MembershipRole, membership_role_id) is None
        assert session.get(Role, role.id) is not None


def test_user_can_have_different_roles_in_different_organizations() -> None:
    """The same user can have different roles in different organizations."""
    with TestingSessionLocal() as session:
        user = create_user(session)

        organization_a = create_organization(session)
        organization_b = create_organization(session)

        membership_a = create_membership(
            session,
            user,
            organization_a,
        )
        membership_b = create_membership(
            session,
            user,
            organization_b,
        )

        manager_role = create_role(
            session,
            name="Manager",
        )
        viewer_role = create_role(
            session,
            name="Viewer",
        )

        session.add_all(
            [
                MembershipRole(
                    membership=membership_a,
                    role=manager_role,
                ),
                MembershipRole(
                    membership=membership_b,
                    role=viewer_role,
                ),
            ]
        )

        session.commit()

        session.refresh(membership_a)
        session.refresh(membership_b)

        assert len(membership_a.membership_roles) == 1
        assert membership_a.membership_roles[0].role.name == "Manager"

        assert len(membership_b.membership_roles) == 1
        assert membership_b.membership_roles[0].role.name == "Viewer"