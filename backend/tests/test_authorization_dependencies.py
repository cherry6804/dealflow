"""Tests for DealFlow authorization dependencies."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.authz.dependencies import require_permission
from app.db.base import Base
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.tenant.dependencies import TenantContext


@pytest.fixture()
def db() -> Session:
    """Create an isolated in-memory database for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)


def create_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        email=f"user-{uuid4()}@example.com",
        display_name="Test User",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(
    db: Session,
    name: str | None = None,
) -> Organization:
    """Create a test organization."""
    organization = Organization(
        name=name or f"Organization {uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


def create_membership(
    db: Session,
    user: User,
    organization: Organization,
    *,
    is_active: bool = True,
) -> Membership:
    """Create a membership connecting a user to an organization."""
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=is_active,
    )
    db.add(membership)
    db.flush()
    return membership


def create_role(
    db: Session,
    name: str | None = None,
    *,
    is_active: bool = True,
) -> Role:
    """Create a test role."""
    role = Role(
        name=name or f"Role {uuid4()}",
        description="Test role",
        is_active=is_active,
    )
    db.add(role)
    db.flush()
    return role


def create_permission(
    db: Session,
    key: str,
    *,
    is_active: bool = True,
) -> Permission:
    """Create a test permission."""
    permission = Permission(
        key=key,
        description="Test permission",
        is_active=is_active,
    )
    db.add(permission)
    db.flush()
    return permission


def assign_role_to_membership(
    db: Session,
    membership: Membership,
    role: Role,
) -> MembershipRole:
    """Assign a role to a membership."""
    membership_role = MembershipRole(
        membership_id=membership.id,
        role_id=role.id,
    )
    db.add(membership_role)
    db.flush()
    return membership_role


def assign_permission_to_role(
    db: Session,
    role: Role,
    permission: Permission,
) -> RolePermission:
    """Assign a permission to a role."""
    role_permission = RolePermission(
        role_id=role.id,
        permission_id=permission.id,
    )
    db.add(role_permission)
    db.flush()
    return role_permission


def create_tenant_context(
    organization: Organization,
    membership: Membership,
) -> TenantContext:
    """Create a verified tenant context for authorization tests."""
    return TenantContext(
        organization=organization,
        membership=membership,
    )


def execute_permission_dependency(
    db: Session,
    tenant_context: TenantContext,
    permission_key: str,
) -> TenantContext:
    """Execute the generated authorization dependency directly."""
    dependency = require_permission(permission_key)

    return dependency(
        tenant_context=tenant_context,
        db=db,
    )


def test_permission_is_granted_when_membership_has_active_role_and_permission(
    db: Session,
) -> None:
    """An active assigned permission allows the operation."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    role = create_role(db)
    permission = create_permission(db, "lead.read")

    assign_role_to_membership(db, membership, role)
    assign_permission_to_role(db, role, permission)

    tenant_context = create_tenant_context(organization, membership)

    result = execute_permission_dependency(
        db,
        tenant_context,
        "lead.read",
    )

    assert result is tenant_context


def test_permission_is_denied_when_membership_has_no_role(
    db: Session,
) -> None:
    """A membership without the required role is denied."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    tenant_context = create_tenant_context(organization, membership)

    with pytest.raises(HTTPException) as exc_info:
        execute_permission_dependency(
            db,
            tenant_context,
            "lead.read",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied."


def test_permission_is_denied_when_role_lacks_permission(
    db: Session,
) -> None:
    """A role without the required permission is denied."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    role = create_role(db)
    assign_role_to_membership(db, membership, role)

    tenant_context = create_tenant_context(organization, membership)

    with pytest.raises(HTTPException) as exc_info:
        execute_permission_dependency(
            db,
            tenant_context,
            "lead.read",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied."


def test_permission_is_denied_when_permission_is_inactive(
    db: Session,
) -> None:
    """An inactive permission cannot authorize an operation."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    role = create_role(db)
    permission = create_permission(
        db,
        "lead.read",
        is_active=False,
    )

    assign_role_to_membership(db, membership, role)
    assign_permission_to_role(db, role, permission)

    tenant_context = create_tenant_context(organization, membership)

    with pytest.raises(HTTPException) as exc_info:
        execute_permission_dependency(
            db,
            tenant_context,
            "lead.read",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied."


def test_permission_is_denied_when_role_is_inactive(
    db: Session,
) -> None:
    """An inactive role cannot authorize an operation."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    role = create_role(
        db,
        is_active=False,
    )
    permission = create_permission(db, "lead.read")

    assign_role_to_membership(db, membership, role)
    assign_permission_to_role(db, role, permission)

    tenant_context = create_tenant_context(organization, membership)

    with pytest.raises(HTTPException) as exc_info:
        execute_permission_dependency(
            db,
            tenant_context,
            "lead.read",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied."


def test_permission_is_denied_when_permission_key_does_not_exist(
    db: Session,
) -> None:
    """An unknown permission key is denied."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    tenant_context = create_tenant_context(organization, membership)

    with pytest.raises(HTTPException) as exc_info:
        execute_permission_dependency(
            db,
            tenant_context,
            "does.not.exist",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied."


def test_permission_is_granted_through_one_of_multiple_roles(
    db: Session,
) -> None:
    """Any active role assigned to the membership may grant permission."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    role_without_permission = create_role(db, "Viewer")
    role_with_permission = create_role(db, "Lead Manager")

    permission = create_permission(db, "lead.update")

    assign_role_to_membership(
        db,
        membership,
        role_without_permission,
    )
    assign_role_to_membership(
        db,
        membership,
        role_with_permission,
    )

    assign_permission_to_role(
        db,
        role_with_permission,
        permission,
    )

    tenant_context = create_tenant_context(organization, membership)

    result = execute_permission_dependency(
        db,
        tenant_context,
        "lead.update",
    )

    assert result is tenant_context


def test_permission_in_one_organization_does_not_authorize_another(
    db: Session,
) -> None:
    """A role assignment in another organization cannot authorize this tenant."""
    user = create_user(db)

    organization_a = create_organization(db, "Organization A")
    organization_b = create_organization(db, "Organization B")

    membership_a = create_membership(
        db,
        user,
        organization_a,
    )
    membership_b = create_membership(
        db,
        user,
        organization_b,
    )

    role = create_role(db)
    permission = create_permission(db, "lead.delete")

    assign_role_to_membership(
        db,
        membership_a,
        role,
    )
    assign_permission_to_role(
        db,
        role,
        permission,
    )

    tenant_context_b = create_tenant_context(
        organization_b,
        membership_b,
    )

    with pytest.raises(HTTPException) as exc_info:
        execute_permission_dependency(
            db,
            tenant_context_b,
            "lead.delete",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied."


def test_permission_key_is_trimmed_before_authorization(
    db: Session,
) -> None:
    """Permission keys are normalized by trimming surrounding whitespace."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user, organization)

    role = create_role(db)
    permission = create_permission(db, "lead.read")

    assign_role_to_membership(db, membership, role)
    assign_permission_to_role(db, role, permission)

    tenant_context = create_tenant_context(organization, membership)

    result = execute_permission_dependency(
        db,
        tenant_context,
        "  lead.read  ",
    )

    assert result is tenant_context


def test_empty_permission_key_is_rejected(
    db: Session,
) -> None:
    """An authorization dependency cannot be created with an empty key."""
    with pytest.raises(ValueError, match="Permission key cannot be empty"):
        require_permission("   ")