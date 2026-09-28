"""Tests for DealFlow authorization dependencies."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import persist_authorization_audit_event
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.audit_event import AuditDecision, AuditEvent
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session
from app.tenant.dependencies import TenantContext


TestingSessionLocal = SessionLocal


def create_user(
    db: Session,
    *,
    email: str | None = None,
    display_name: str | None = None,
    is_active: bool = True,
) -> User:
    """Create a unique active test user."""
    user = User(
        email=email or f"user-{uuid4()}@example.com",
        display_name=display_name or f"Test User {uuid4()}",
        password_hash="test-password-hash",
        is_active=is_active,
    )

    db.add(user)
    db.flush()

    return user


def create_organization(
    db: Session,
    *,
    name: str | None = None,
    is_active: bool = True,
) -> Organization:
    """Create a unique active test organization."""
    organization = Organization(
        name=name or f"Test Organization-{uuid4()}",
        is_active=is_active,
    )

    db.add(organization)
    db.flush()

    return organization


def create_membership(
    db: Session,
    *,
    user: User,
    organization: Organization,
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
    *,
    name: str | None = None,
    is_active: bool = True,
) -> Role:
    """Create a unique test role."""
    role = Role(
        name=name or f"Test Role-{uuid4()}",
        is_active=is_active,
    )

    db.add(role)
    db.flush()

    return role


def create_permission(
    db: Session,
    *,
    key: str | None = None,
    is_active: bool = True,
) -> Permission:
    """Create a unique test permission."""
    permission = Permission(
        key=key or f"test.permission.{uuid4()}",
        is_active=is_active,
    )

    db.add(permission)
    db.flush()

    return permission


def assign_role_to_membership(
    db: Session,
    *,
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
    *,
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


def create_test_app(
    required_permission_key: str,
) -> FastAPI:
    """Create a minimal FastAPI application for authorization testing."""
    app = FastAPI()

    def override_get_db_session():
        """Provide a database session to the test application."""
        db = TestingSessionLocal()

        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session

    def override_current_user() -> CurrentUserContext:
        """Placeholder authentication dependency for this test app."""
        raise RuntimeError(
            "The current-user dependency must be overridden by the test.",
        )

    app.dependency_overrides[get_current_user_context] = override_current_user

    @app.get("/protected")
    def protected_endpoint(
        tenant_context: TenantContext = Depends(
            require_permission(required_permission_key),
        ),
    ) -> dict[str, str]:
        """Protected endpoint used to exercise authorization."""
        return {
            "status": "ok",
            "organization_id": str(tenant_context.organization_id),
        }

    return app


@contextmanager
def make_test_client(
    required_permission_key: str,
    *,
    user: User,
) -> TestClient:
    """Create a test client with the supplied authenticated user."""
    app = create_test_app(required_permission_key)

    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )

    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Set the tenant-selection header for the test client."""
    client.headers.update(
        {
            "X-Organization-ID": str(organization.id),
        },
    )


def find_latest_audit_event(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    permission_key: str,
) -> AuditEvent | None:
    """Find the latest authorization audit event for a test."""
    statement = (
        select(AuditEvent)
        .where(
            AuditEvent.user_id == user_id,
            AuditEvent.organization_id == organization_id,
            AuditEvent.permission_key == permission_key,
        )
        .order_by(
            AuditEvent.occurred_at.desc(),
            AuditEvent.id.desc(),
        )
        .limit(1)
    )

    return db.scalar(statement)


def test_permission_dependency_rejects_empty_permission_key() -> None:
    """Reject an empty permission key."""
    with pytest.raises(
        ValueError,
        match="Permission key cannot be empty",
    ):
        require_permission("   ")


def test_permission_dependency_grants_access_when_permission_exists() -> None:
    """Grant access when the membership has the required permission."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )

        role = create_role(db)

        permission = create_permission(
            db,
            key=permission_key,
        )

        assign_role_to_membership(
            db,
            membership=membership,
            role=role,
        )

        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        db.commit()

        with make_test_client(
            permission_key,
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization,
            )

            response = client.get("/protected")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "organization_id": str(organization.id),
        }

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.ALLOWED.value
        assert audit_event.action == permission_key


def test_permission_dependency_denies_missing_permission() -> None:
    """Deny access when the membership lacks the required permission."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        db.commit()

        with make_test_client(
            permission_key,
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization,
            )

            response = client.get("/protected")

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.DENIED.value
        assert audit_event.action == permission_key


def test_permission_dependency_denies_inactive_permission() -> None:
    """Deny access when the permission is inactive."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )

        role = create_role(db)

        permission = create_permission(
            db,
            key=permission_key,
            is_active=False,
        )

        assign_role_to_membership(
            db,
            membership=membership,
            role=role,
        )

        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        db.commit()

        with make_test_client(
            permission_key,
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization,
            )

            response = client.get("/protected")

        assert response.status_code == 403

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.DENIED.value


def test_permission_dependency_denies_inactive_role() -> None:
    """Deny access when the assigned role is inactive."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )

        role = create_role(
            db,
            is_active=False,
        )

        permission = create_permission(
            db,
            key=permission_key,
        )

        assign_role_to_membership(
            db,
            membership=membership,
            role=role,
        )

        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        db.commit()

        with make_test_client(
            permission_key,
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization,
            )

            response = client.get("/protected")

        assert response.status_code == 403

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.DENIED.value


def test_permission_dependency_allows_through_one_of_multiple_roles() -> None:
    """Grant access when any active role provides the permission."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )

        first_role = create_role(
            db,
            name=f"First Role-{uuid4()}",
        )

        second_role = create_role(
            db,
            name=f"Second Role-{uuid4()}",
        )

        permission = create_permission(
            db,
            key=permission_key,
        )

        assign_role_to_membership(
            db,
            membership=membership,
            role=first_role,
        )

        assign_role_to_membership(
            db,
            membership=membership,
            role=second_role,
        )

        assign_permission_to_role(
            db,
            role=second_role,
            permission=permission,
        )

        db.commit()

        with make_test_client(
            permission_key,
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization,
            )

            response = client.get("/protected")

        assert response.status_code == 200

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.ALLOWED.value


def test_permission_dependency_preserves_cross_organization_isolation() -> None:
    """Deny access when permission exists only in another organization."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)

        organization_a = create_organization(db)
        organization_b = create_organization(db)

        membership_a = create_membership(
            db,
            user=user,
            organization=organization_a,
        )

        membership_b = create_membership(
            db,
            user=user,
            organization=organization_b,
        )

        role_b = create_role(
            db,
            name=f"Organization B Role-{uuid4()}",
        )

        permission = create_permission(
            db,
            key=permission_key,
        )

        assign_role_to_membership(
            db,
            membership=membership_b,
            role=role_b,
        )

        assign_permission_to_role(
            db,
            role=role_b,
            permission=permission,
        )

        db.commit()

        with make_test_client(
            permission_key,
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization_a,
            )

            response = client.get("/protected")

        assert response.status_code == 403

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization_a.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.DENIED.value

        organization_b_audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization_b.id,
            permission_key=permission_key,
        )

        assert organization_b_audit_event is None

        assert membership_a.organization_id == organization_a.id


def test_permission_key_whitespace_is_normalized() -> None:
    """Normalize surrounding permission-key whitespace."""
    permission_key = f"lead.read.{uuid4()}"

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )

        role = create_role(db)

        permission = create_permission(
            db,
            key=permission_key,
        )

        assign_role_to_membership(
            db,
            membership=membership,
            role=role,
        )

        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        db.commit()

        with make_test_client(
            f"  {permission_key}  ",
            user=user,
        ) as client:
            add_tenant_header(
                client,
                organization,
            )

            response = client.get("/protected")

        assert response.status_code == 200

        audit_event = find_latest_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            permission_key=permission_key,
        )

        assert audit_event is not None
        assert audit_event.decision == AuditDecision.ALLOWED.value
        assert audit_event.permission_key == permission_key
        assert audit_event.action == permission_key


def test_persist_authorization_audit_event_uses_independent_transaction() -> None:
    """Persist authorization audit events independently."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        db.commit()

        event = persist_authorization_audit_event(
            user_id=user.id,
            organization_id=organization.id,
            action="lead.read",
            decision=AuditDecision.ALLOWED,
            permission_key="lead.read",
        )

        assert event.id is not None

        persisted = db.get(
            AuditEvent,
            event.id,
        )

        assert persisted is not None
        assert persisted.decision == AuditDecision.ALLOWED.value
        assert persisted.permission_key == "lead.read"