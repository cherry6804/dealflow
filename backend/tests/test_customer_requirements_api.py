"""Tests for DealFlow Customer Requirement API routes."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from decimal import Decimal
from app.api.requirements import router as requirements_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import (
    CustomerRequirementLocation,
)
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

def test_create_customer_requirement_returns_empty_budget_by_default() -> None:
    """DF-51: A new requirement has no captured budget by default."""

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

        assert payload["budget_min"] is None
        assert payload["budget_max"] is None
        assert payload["budget_currency"] is None


def test_update_customer_requirement_budget_successfully() -> None:
    """DF-51: Capture a complete budget range."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "5000000.00",
                    "budget_max": "10000000.00",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert Decimal(payload["budget_min"]) == Decimal("5000000.00")
        assert Decimal(payload["budget_max"]) == Decimal("10000000.00")
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_supports_minimum_only() -> None:
    """DF-51: A requirement can capture only a minimum budget."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "5000000.00",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert Decimal(payload["budget_min"]) == Decimal("5000000.00")
        assert payload["budget_max"] is None
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_supports_maximum_only() -> None:
    """DF-51: A requirement can capture only a maximum budget."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_max": "10000000.00",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["budget_min"] is None
        assert Decimal(payload["budget_max"]) == Decimal("10000000.00")
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_accepts_equal_values() -> None:
    """DF-51: Equal minimum and maximum budgets are valid."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "7500000.50",
                    "budget_max": "7500000.50",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert Decimal(payload["budget_min"]) == Decimal("7500000.50")
        assert Decimal(payload["budget_max"]) == Decimal("7500000.50")
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_normalizes_currency() -> None:
    """DF-51: Currency codes are normalized to uppercase."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_max": "10000000",
                    "budget_currency": "inr",
                },
            )

        assert response.status_code == 200
        assert response.json()["budget_currency"] == "INR"


def test_update_customer_requirement_budget_rejects_negative_minimum() -> None:
    """DF-51: Negative minimum budgets are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "-1.00",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_budget_rejects_negative_maximum() -> None:
    """DF-51: Negative maximum budgets are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_max": "-1.00",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_budget_rejects_minimum_greater_than_maximum() -> None:
    """DF-51: Minimum budget cannot exceed maximum budget."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "10000000",
                    "budget_max": "5000000",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_budget_requires_currency() -> None:
    """DF-51: A captured budget requires a currency."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "5000000",
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Budget currency is required when a budget value is provided."
        }


def test_update_customer_requirement_budget_preserves_omitted_fields() -> None:
    """DF-51: PATCH preserves budget fields that are omitted."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        requirement.budget_min = Decimal("5000000.00")
        requirement.budget_max = Decimal("10000000.00")
        requirement.budget_currency = "INR"
        db.commit()
        db.refresh(requirement)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_max": "12000000.00",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert Decimal(payload["budget_min"]) == Decimal("5000000.00")
        assert Decimal(payload["budget_max"]) == Decimal("12000000.00")
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_explicit_null_clears_field() -> None:
    """DF-51: Explicit null clears only the supplied budget field."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        requirement.budget_min = Decimal("5000000.00")
        requirement.budget_max = Decimal("10000000.00")
        requirement.budget_currency = "INR"
        db.commit()
        db.refresh(requirement)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": None,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["budget_min"] is None
        assert Decimal(payload["budget_max"]) == Decimal("10000000.00")
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_empty_patch_preserves_values() -> None:
    """DF-51: An empty PATCH does not change budget information."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        requirement.budget_min = Decimal("5000000.00")
        requirement.budget_max = Decimal("10000000.00")
        requirement.budget_currency = "INR"
        db.commit()
        db.refresh(requirement)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={},
            )

        assert response.status_code == 200

        payload = response.json()

        assert Decimal(payload["budget_min"]) == Decimal("5000000.00")
        assert Decimal(payload["budget_max"]) == Decimal("10000000.00")
        assert payload["budget_currency"] == "INR"


def test_update_customer_requirement_budget_rejects_currency_without_budget() -> None:
    """DF-51: Currency cannot exist without a budget value."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Budget currency cannot be set without a budget value."
        }


def test_update_customer_requirement_budget_can_clear_complete_budget() -> None:
    """DF-51: Minimum, maximum, and currency can all be explicitly cleared."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        requirement.budget_min = Decimal("5000000.00")
        requirement.budget_max = Decimal("10000000.00")
        requirement.budget_currency = "INR"
        db.commit()
        db.refresh(requirement)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": None,
                    "budget_max": None,
                    "budget_currency": None,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["budget_min"] is None
        assert payload["budget_max"] is None
        assert payload["budget_currency"] is None


def test_update_customer_requirement_budget_returns_404_for_missing_requirement() -> None:
    """DF-51: Updating a missing requirement returns 404."""

    permission_key = "requirements.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{uuid4()}",
                json={
                    "budget_min": "5000000",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_update_customer_requirement_budget_prevents_cross_tenant_access() -> None:
    """DF-51: A requirement cannot be updated from another tenant."""

    permission_key = "requirements.update"

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

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement_b.id}",
                json={
                    "budget_min": "5000000",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_update_customer_requirement_budget_requires_permission() -> None:
    """DF-51: Updating budget requires requirements.update permission."""

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

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "5000000",
                    "budget_currency": "INR",
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_budget_rejects_invalid_currency() -> None:
    """DF-51: Currency must be a three-letter alphabetic code."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/customer-requirements/{requirement.id}",
                json={
                    "budget_min": "5000000",
                    "budget_currency": "12",
                },
            )

        assert response.status_code == 422

def test_create_customer_requirement_location_successfully() -> None:
    """DF-52: Create a location for a customer requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": " Chennai ",
                    "locality": " Tambaram ",
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["customer_requirement_id"] == str(requirement.id)
        assert payload["city"] == "Chennai"
        assert payload["locality"] == "Tambaram"
        assert payload["is_active"] is True
        assert payload["created_at"]
        assert payload["updated_at"]


def test_create_customer_requirement_location_persists_record() -> None:
    """DF-52: Created locations are persisted for the requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Velachery",
                },
            )

        assert response.status_code == 201

        location_id = UUID(response.json()["id"])

        persisted_location = db.scalar(
            select(CustomerRequirementLocation).where(
                CustomerRequirementLocation.id == location_id,
                CustomerRequirementLocation.organization_id
                == organization.id,
                CustomerRequirementLocation.customer_requirement_id
                == requirement.id,
            )
        )

        assert persisted_location is not None
        assert persisted_location.city == "Chennai"
        assert persisted_location.locality == "Velachery"
        assert persisted_location.is_active is True


def test_create_customer_requirement_location_supports_multiple_locations() -> None:
    """DF-52: A requirement can contain multiple preferred locations."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            first_response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Tambaram",
                },
            )

            second_response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Velachery",
                },
            )

        assert first_response.status_code == 201
        assert second_response.status_code == 201

        with TestingSessionLocal() as verification_db:
            locations = list(
                verification_db.scalars(
                    select(CustomerRequirementLocation)
                    .where(
                        CustomerRequirementLocation.organization_id
                        == organization.id,
                        CustomerRequirementLocation.customer_requirement_id
                        == requirement.id,
                    )
                    .order_by(CustomerRequirementLocation.created_at.asc())
                ).all()
            )

        assert len(locations) == 2
        assert {location.locality for location in locations} == {
            "Tambaram",
            "Velachery",
        }


def test_create_customer_requirement_location_rejects_blank_city() -> None:
    """DF-52: Blank city values are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "   ",
                    "locality": "Tambaram",
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_location_rejects_blank_locality() -> None:
    """DF-52: Blank locality values are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "   ",
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_location_rejects_unknown_fields() -> None:
    """DF-52: Location creation rejects fields outside the contract."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Tambaram",
                    "organization_id": str(organization.id),
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_location_returns_404_for_missing_requirement() -> None:
    """DF-52: A location cannot be created for a missing requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{uuid4()}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Tambaram",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_create_customer_requirement_location_prevents_cross_tenant_access() -> None:
    """DF-52: A location cannot be created for another tenant's requirement."""

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        organization_b = create_organization(db)

        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement_b.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Tambaram",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_create_customer_requirement_location_requires_update_permission() -> None:
    """DF-52: Creating a location requires requirements.update."""

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

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
                json={
                    "city": "Chennai",
                    "locality": "Tambaram",
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_list_customer_requirement_locations_successfully() -> None:
    """DF-52: List all locations belonging to a requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        first_location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        second_location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Velachery",
            is_active=True,
        )

        db.add_all([first_location, second_location])
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
            )

        assert response.status_code == 200

        payload = response.json()

        assert len(payload) == 2
        assert payload[0]["customer_requirement_id"] == str(requirement.id)
        assert payload[1]["customer_requirement_id"] == str(requirement.id)
        assert {item["locality"] for item in payload} == {
            "Tambaram",
            "Velachery",
        }


def test_list_customer_requirement_locations_returns_empty_list() -> None:
    """DF-52: A requirement can exist without preferred locations."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
            )

        assert response.status_code == 200
        assert response.json() == []


def test_list_customer_requirement_locations_prevents_cross_tenant_access() -> None:
    """DF-52: Locations cannot be listed from another tenant."""

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        organization_b = create_organization(db)

        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )

        location_b = CustomerRequirementLocation(
            organization_id=organization_b.id,
            customer_requirement_id=requirement_b.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location_b)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement_b.id}/locations",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_list_customer_requirement_locations_requires_read_permission() -> None:
    """DF-52: Listing locations requires requirements.read."""

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

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}/locations",
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_location_successfully() -> None:
    """DF-52: Update city, locality, and active state."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location)
        db.commit()
        db.refresh(location)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{location.id}"
                ),
                json={
                    "city": "Chennai",
                    "locality": "Tambaram East",
                    "is_active": False,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["id"] == str(location.id)
        assert payload["city"] == "Chennai"
        assert payload["locality"] == "Tambaram East"
        assert payload["is_active"] is False


def test_update_customer_requirement_location_preserves_omitted_fields() -> None:
    """DF-52: PATCH preserves location fields that are omitted."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location)
        db.commit()
        db.refresh(location)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{location.id}"
                ),
                json={
                    "locality": "Tambaram East",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["city"] == "Chennai"
        assert payload["locality"] == "Tambaram East"
        assert payload["is_active"] is True


def test_update_customer_requirement_location_explicit_null_does_not_clear_required_fields() -> None:
    """DF-52: Required location fields cannot be cleared with null."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location)
        db.commit()
        db.refresh(location)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{location.id}"
                ),
                json={
                    "city": None,
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_location_rejects_blank_values() -> None:
    """DF-52: Required location text cannot be blank."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location)
        db.commit()
        db.refresh(location)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{location.id}"
                ),
                json={
                    "locality": "   ",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_location_returns_404_for_missing_location() -> None:
    """DF-52: Updating a missing location returns 404."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{uuid4()}"
                ),
                json={
                    "locality": "Tambaram East",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement location not found.",
        }


def test_update_customer_requirement_location_prevents_cross_tenant_access() -> None:
    """DF-52: A location cannot be updated from another tenant."""

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        organization_b = create_organization(db)

        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )

        location_b = CustomerRequirementLocation(
            organization_id=organization_b.id,
            customer_requirement_id=requirement_b.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location_b)
        db.commit()
        db.refresh(location_b)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement_b.id}"
                    f"/locations/{location_b.id}"
                ),
                json={
                    "locality": "Tambaram East",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement location not found.",
        }


def test_update_customer_requirement_location_requires_update_permission() -> None:
    """DF-52: Updating a location requires requirements.update."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location)
        db.commit()
        db.refresh(location)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{location.id}"
                ),
                json={
                    "locality": "Tambaram East",
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_location_can_deactivate_without_deleting() -> None:
    """DF-52: Deactivation retains the location record."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        location = CustomerRequirementLocation(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            city="Chennai",
            locality="Tambaram",
            is_active=True,
        )

        db.add(location)
        db.commit()
        db.refresh(location)

        location_id = location.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/locations/{location.id}"
                ),
                json={
                    "is_active": False,
                },
            )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

        with TestingSessionLocal() as verification_db:
            persisted_location = verification_db.scalar(
                select(CustomerRequirementLocation).where(
                    CustomerRequirementLocation.id == location_id,
                    CustomerRequirementLocation.organization_id
                    == organization.id,
                )
            )

        assert persisted_location is not None
        assert persisted_location.is_active is False