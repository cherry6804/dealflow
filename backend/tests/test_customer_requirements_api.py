"""Tests for DealFlow Customer Requirement API routes."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.requirements import router as requirements_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session


TestingSessionLocal = SessionLocal


def create_user(
    db: Session,
    *,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    """Create a unique test user."""

    user = User(
        email=email or f"user-{uuid4()}@example.com",
        display_name=f"Test User {uuid4()}",
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
    """Create a unique test organization."""

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


def get_or_create_permission(
    db: Session,
    *,
    key: str,
    is_active: bool = True,
) -> Permission:
    """Return an existing permission or create it when absent."""

    permission = db.scalar(
        select(Permission).where(
            Permission.key == key,
        )
    )

    if permission is not None:
        if permission.is_active != is_active:
            permission.is_active = is_active
            db.flush()

        return permission

    permission = Permission(
        key=key,
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


def create_authorized_user(
    db: Session,
    *,
    permission_key: str,
) -> tuple[User, Organization]:
    """Create a user, tenant, membership, role, and permission grant."""

    user = create_user(db)
    organization = create_organization(db)

    membership = create_membership(
        db,
        user=user,
        organization=organization,
    )

    role = create_role(db)

    permission = get_or_create_permission(
        db,
        key=permission_key,
        is_active=True,
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

    return user, organization


def create_customer_requirement(
    db: Session,
    *,
    organization: Organization,
    status: str = CustomerRequirement.STATUS_ACTIVE,
    is_active: bool = True,
) -> CustomerRequirement:
    """Create and persist a Customer Requirement for a test tenant."""

    requirement = CustomerRequirement(
        organization_id=organization.id,
        status=status,
        is_active=is_active,
    )

    db.add(requirement)
    db.commit()
    db.refresh(requirement)

    return requirement


def create_test_app(
    *,
    user: User,
) -> FastAPI:
    """Create a Customer Requirement API test application."""

    app = FastAPI()
    app.include_router(requirements_router)

    def override_get_db_session():
        """Provide a database session to the test application."""

        db = TestingSessionLocal()

        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session

    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )

    return app


@contextmanager
def make_test_client(
    *,
    user: User,
):
    """Create a Customer Requirement API test client."""

    app = create_test_app(user=user)

    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Set the tenant-selection header."""

    client.headers.update(
        {
            "X-Organization-ID": str(organization.id),
        }
    )


def test_create_customer_requirement_successfully() -> None:
    """Create a Customer Requirement within the verified tenant."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["status"] == CustomerRequirement.STATUS_ACTIVE
        assert payload["is_active"] is True
        assert payload["created_at"]
        assert payload["updated_at"]


def test_create_customer_requirement_generates_server_id() -> None:
    """The Customer Requirement ID is generated by the server."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 201

        requirement_id = UUID(response.json()["id"])

        persisted_requirement = db.scalar(
            select(CustomerRequirement).where(
                CustomerRequirement.id == requirement_id,
                CustomerRequirement.organization_id == organization.id,
            )
        )

        assert persisted_requirement is not None


def test_create_customer_requirement_rejects_client_organization_id() -> None:
    """The requirement organization comes from tenant context."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        other_organization = create_organization(db)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={
                    "organization_id": str(other_organization.id),
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_rejects_client_fields() -> None:
    """Reject fields that are not part of the DF-50 create contract."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={
                    "budget": 5000000,
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_requires_permission() -> None:
    """Reject creation when requirements.create is missing."""

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_create_customer_requirement_requires_tenant_context() -> None:
    """Reject creation without tenant context."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, _ = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_get_customer_requirement_successfully() -> None:
    """Retrieve a Customer Requirement within the verified tenant."""

    permission_key = "requirements.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}",
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["id"] == str(requirement.id)
        assert payload["organization_id"] == str(organization.id)
        assert payload["status"] == CustomerRequirement.STATUS_ACTIVE
        assert payload["is_active"] is True


def test_get_customer_requirement_returns_404_for_missing_requirement() -> None:
    """Return 404 when the Customer Requirement does not exist."""

    permission_key = "requirements.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{uuid4()}",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_get_customer_requirement_prevents_cross_tenant_access() -> None:
    """Do not expose a Customer Requirement owned by another tenant."""

    permission_key = "requirements.read"

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        organization_b = create_organization(db)

        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement_b.id}",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_get_customer_requirement_requires_permission() -> None:
    """Reject retrieval when requirements.read is missing."""

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}",
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_get_customer_requirement_requires_tenant_context() -> None:
    """Reject retrieval without tenant context."""

    permission_key = "requirements.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}",
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_get_customer_requirement_validates_requirement_id() -> None:
    """Require the Customer Requirement identifier to be a valid UUID."""

    permission_key = "requirements.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/customer-requirements/not-a-uuid",
            )

        assert response.status_code == 422