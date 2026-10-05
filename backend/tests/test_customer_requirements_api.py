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
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.customer_requirement_possession_parking_preference import (
    CustomerRequirementPossessionParkingPreference,
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

# ---------------------------------------------------------------------------
# DF-53: Customer Requirement Property Type & BHK Preferences
# ---------------------------------------------------------------------------


def test_create_customer_requirement_property_preference_successfully() -> None:
    """DF-53: Create a property type and BHK preference."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 2,
                    "bhk_max": 3,
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["customer_requirement_id"] == str(requirement.id)
        assert payload["property_type"] == "APARTMENT"
        assert payload["bhk_min"] == 2
        assert payload["bhk_max"] == 3
        assert payload["is_active"] is True


def test_create_customer_requirement_property_preference_persists() -> None:
    """DF-53: Created property preferences are persisted."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "VILLA",
                    "bhk_min": 4,
                    "bhk_max": 5,
                },
            )

        assert response.status_code == 201

        preference_id = UUID(response.json()["id"])

    with TestingSessionLocal() as verification_db:
        persisted_preference = verification_db.scalar(
            select(CustomerRequirementPropertyPreference).where(
                CustomerRequirementPropertyPreference.id == preference_id,
                CustomerRequirementPropertyPreference.organization_id
                == organization.id,
                CustomerRequirementPropertyPreference.customer_requirement_id
                == requirement.id,
            )
        )

    assert persisted_preference is not None
    assert persisted_preference.property_type == "VILLA"
    assert persisted_preference.bhk_min == 4
    assert persisted_preference.bhk_max == 5
    assert persisted_preference.is_active is True


def test_create_customer_requirement_property_preference_supports_all_property_types() -> None:
    """DF-53: All supported property types can be persisted."""

    property_types = (
        "APARTMENT",
        "VILLA",
        "INDEPENDENT_HOUSE",
        "PLOT",
        "COMMERCIAL",
        "OTHER",
    )

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

            for property_type in property_types:
                response = client.post(
                    f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                    json={
                        "property_type": property_type,
                    },
                )

                assert response.status_code == 201
                assert response.json()["property_type"] == property_type
                assert response.json()["bhk_min"] is None
                assert response.json()["bhk_max"] is None


def test_create_customer_requirement_property_preference_supports_exact_bhk() -> None:
    """DF-53: Exact BHK is represented by equal minimum and maximum values."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 2,
                    "bhk_max": 2,
                },
            )

        assert response.status_code == 201
        assert response.json()["bhk_min"] == 2
        assert response.json()["bhk_max"] == 2


def test_create_customer_requirement_property_preference_supports_minimum_only_bhk() -> None:
    """DF-53: A minimum-only BHK preference is supported."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "VILLA",
                    "bhk_min": 3,
                },
            )

        assert response.status_code == 201
        assert response.json()["bhk_min"] == 3
        assert response.json()["bhk_max"] is None


def test_create_customer_requirement_property_preference_supports_no_bhk() -> None:
    """DF-53: A property preference can omit BHK entirely."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "PLOT",
                },
            )

        assert response.status_code == 201
        assert response.json()["bhk_min"] is None
        assert response.json()["bhk_max"] is None


def test_create_customer_requirement_property_preference_rejects_invalid_property_type() -> None:
    """DF-53: Property type must use the controlled vocabulary."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "FARMHOUSE",
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_property_preference_rejects_non_positive_bhk() -> None:
    """DF-53: BHK values must be positive whole numbers."""

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

            zero_response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 0,
                },
            )

            negative_response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_max": -1,
                },
            )

        assert zero_response.status_code == 422
        assert negative_response.status_code == 422


def test_create_customer_requirement_property_preference_rejects_invalid_bhk_range() -> None:
    """DF-53: BHK minimum cannot exceed BHK maximum."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 4,
                    "bhk_max": 2,
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_property_preference_rejects_unknown_fields() -> None:
    """DF-53: Client-controlled fields outside the contract are rejected."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 2,
                    "bhk_max": 3,
                    "organization_id": str(organization.id),
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_property_preference_returns_404_for_missing_requirement() -> None:
    """DF-53: A preference cannot be created for a missing requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/customer-requirements/{uuid4()}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 2,
                    "bhk_max": 3,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_create_customer_requirement_property_preference_prevents_cross_tenant_access() -> None:
    """DF-53: A preference cannot be created for another tenant's requirement."""

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
                f"/api/v1/customer-requirements/{requirement_b.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 2,
                    "bhk_max": 3,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_create_customer_requirement_property_preference_requires_update_permission() -> None:
    """DF-53: Creating a preference requires requirements.update."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
                json={
                    "property_type": "APARTMENT",
                    "bhk_min": 2,
                    "bhk_max": 3,
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_list_customer_requirement_property_preferences_successfully() -> None:
    """DF-53: List all preferences belonging to a requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        first_preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        second_preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="VILLA",
            bhk_min=4,
            bhk_max=None,
            is_active=True,
        )

        db.add_all([first_preference, second_preference])
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
            )

        assert response.status_code == 200

        payload = response.json()

        assert len(payload) == 2

        preferences_by_type = {
            item["property_type"]: item
            for item in payload
        }

        assert preferences_by_type["APARTMENT"]["bhk_min"] == 2
        assert preferences_by_type["APARTMENT"]["bhk_max"] == 3

        assert preferences_by_type["VILLA"]["bhk_min"] == 4
        assert preferences_by_type["VILLA"]["bhk_max"] is None


def test_list_customer_requirement_property_preferences_returns_empty_list() -> None:
    """DF-53: A requirement without preferences returns an empty list."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
            )

        assert response.status_code == 200
        assert response.json() == []


def test_list_customer_requirement_property_preferences_returns_404_for_missing_requirement() -> None:
    """DF-53: Preferences cannot be listed for a missing requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/customer-requirements/{uuid4()}/property-preferences",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_list_customer_requirement_property_preferences_prevents_cross_tenant_access() -> None:
    """DF-53: Preferences cannot be listed from another tenant."""

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

        preference_b = CustomerRequirementPropertyPreference(
            organization_id=organization_b.id,
            customer_requirement_id=requirement_b.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference_b)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get(
                f"/api/v1/customer-requirements/{requirement_b.id}/property-preferences",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_list_customer_requirement_property_preferences_requires_read_permission() -> None:
    """DF-53: Listing preferences requires requirements.read."""

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
                f"/api/v1/customer-requirements/{requirement.id}/property-preferences",
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_property_preference_successfully() -> None:
    """DF-53: Update property type and BHK preference values."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "property_type": "VILLA",
                    "bhk_min": 4,
                    "bhk_max": 5,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["property_type"] == "VILLA"
        assert payload["bhk_min"] == 4
        assert payload["bhk_max"] == 5
        assert payload["is_active"] is True


def test_update_customer_requirement_property_preference_preserves_omitted_fields() -> None:
    """DF-53: Omitted PATCH fields remain unchanged."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "is_active": False,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["property_type"] == "APARTMENT"
        assert payload["bhk_min"] == 2
        assert payload["bhk_max"] == 3
        assert payload["is_active"] is False


def test_update_customer_requirement_property_preference_explicit_null_clears_bhk() -> None:
    """DF-53: Explicit null clears nullable BHK fields."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "bhk_min": None,
                    "bhk_max": None,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["property_type"] == "APARTMENT"
        assert payload["bhk_min"] is None
        assert payload["bhk_max"] is None


def test_update_customer_requirement_property_preference_rejects_invalid_final_bhk_range() -> None:
    """DF-53: PATCH validates the resulting BHK range, not only supplied fields."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "bhk_min": 4,
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "BHK minimum cannot be greater than BHK maximum.",
        }


def test_update_customer_requirement_property_preference_rejects_null_property_type() -> None:
    """DF-53: Persisted preferences cannot have a null property type."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "property_type": None,
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Property type cannot be cleared.",
        }


def test_update_customer_requirement_property_preference_rejects_unknown_fields() -> None:
    """DF-53: Unknown PATCH fields are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "unknown_field": "not-allowed",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_property_preference_returns_404_for_missing_preference() -> None:
    """DF-53: Updating a missing preference returns 404."""

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
                    f"/property-preferences/{uuid4()}"
                ),
                json={
                    "bhk_min": 3,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement property preference not found.",
        }


def test_update_customer_requirement_property_preference_prevents_cross_tenant_access() -> None:
    """DF-53: A preference cannot be updated from another tenant."""

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

        preference_b = CustomerRequirementPropertyPreference(
            organization_id=organization_b.id,
            customer_requirement_id=requirement_b.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference_b)
        db.commit()
        db.refresh(preference_b)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement_b.id}"
                    f"/property-preferences/{preference_b.id}"
                ),
                json={
                    "property_type": "VILLA",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement property preference not found.",
        }


def test_update_customer_requirement_property_preference_requires_update_permission() -> None:
    """DF-53: Updating a preference requires requirements.update."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "property_type": "VILLA",
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_property_preference_can_deactivate_without_deleting() -> None:
    """DF-53: Deactivation retains the property preference record."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPropertyPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_type="APARTMENT",
            bhk_min=2,
            bhk_max=3,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        preference_id = preference.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    f"/property-preferences/{preference.id}"
                ),
                json={
                    "is_active": False,
                },
            )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    with TestingSessionLocal() as verification_db:
        persisted_preference = verification_db.scalar(
            select(CustomerRequirementPropertyPreference).where(
                CustomerRequirementPropertyPreference.id == preference_id,
                CustomerRequirementPropertyPreference.organization_id
                == organization.id,
            )
        )

    assert persisted_preference is not None
    assert persisted_preference.is_active is False
    assert persisted_preference.property_type == "APARTMENT"
    assert persisted_preference.bhk_min == 2
    assert persisted_preference.bhk_max == 3

# ---------------------------------------------------------------------------
# DF-54: Customer Requirement Possession & Parking Preferences
# ---------------------------------------------------------------------------


def test_create_customer_requirement_possession_parking_preference_successfully() -> None:
    """DF-54: Create possession and parking preferences."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "READY_TO_MOVE",
                    "parking_preference": "REQUIRED",
                    "parking_spaces_min": 2,
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["customer_requirement_id"] == str(requirement.id)
        assert payload["possession_preference"] == "READY_TO_MOVE"
        assert payload["parking_preference"] == "REQUIRED"
        assert payload["parking_spaces_min"] == 2
        assert payload["is_active"] is True
        assert payload["created_at"]
        assert payload["updated_at"]


def test_create_customer_requirement_possession_parking_preference_persists() -> None:
    """DF-54: Created possession and parking preferences are persisted."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "WITHIN_12_MONTHS",
                    "parking_preference": "PREFERRED",
                    "parking_spaces_min": 1,
                },
            )

        assert response.status_code == 201

        preference_id = UUID(response.json()["id"])

    with TestingSessionLocal() as verification_db:
        persisted_preference = verification_db.scalar(
            select(CustomerRequirementPossessionParkingPreference).where(
                CustomerRequirementPossessionParkingPreference.id
                == preference_id,
                CustomerRequirementPossessionParkingPreference.organization_id
                == organization.id,
                CustomerRequirementPossessionParkingPreference.customer_requirement_id
                == requirement.id,
            )
        )

    assert persisted_preference is not None
    assert persisted_preference.possession_preference == "WITHIN_12_MONTHS"
    assert persisted_preference.parking_preference == "PREFERRED"
    assert persisted_preference.parking_spaces_min == 1
    assert persisted_preference.is_active is True


def test_create_customer_requirement_possession_parking_preference_supports_all_possession_values() -> None:
    """DF-54: All supported possession values can be persisted."""

    possession_values = (
        "READY_TO_MOVE",
        "WITHIN_3_MONTHS",
        "WITHIN_6_MONTHS",
        "WITHIN_12_MONTHS",
        "AFTER_12_MONTHS",
        "ANY",
    )

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        for possession_preference in possession_values:
            requirement = create_customer_requirement(
                db,
                organization=organization,
            )

            with make_test_client(user=user) as client:
                add_tenant_header(client, organization)

                response = client.post(
                    (
                        f"/api/v1/customer-requirements/{requirement.id}"
                        "/possession-parking-preference"
                    ),
                    json={
                        "possession_preference": possession_preference,
                        "parking_preference": "ANY",
                    },
                )

            assert response.status_code == 201
            assert response.json()["possession_preference"] == possession_preference


def test_create_customer_requirement_possession_parking_preference_supports_all_parking_values() -> None:
    """DF-54: All supported parking values can be persisted."""

    parking_values = (
        "REQUIRED",
        "PREFERRED",
        "NOT_REQUIRED",
        "ANY",
    )

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        for parking_preference in parking_values:
            requirement = create_customer_requirement(
                db,
                organization=organization,
            )

            with make_test_client(user=user) as client:
                add_tenant_header(client, organization)

                response = client.post(
                    (
                        f"/api/v1/customer-requirements/{requirement.id}"
                        "/possession-parking-preference"
                    ),
                    json={
                        "possession_preference": "ANY",
                        "parking_preference": parking_preference,
                    },
                )

            assert response.status_code == 201
            assert response.json()["parking_preference"] == parking_preference


def test_create_customer_requirement_possession_parking_preference_supports_optional_parking_spaces() -> None:
    """DF-54: Minimum parking spaces are optional."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "ANY",
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["parking_spaces_min"] is None


def test_create_customer_requirement_possession_parking_preference_rejects_duplicate() -> None:
    """DF-54: A requirement can have only one possession/parking record."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "READY_TO_MOVE",
                    "parking_preference": "REQUIRED",
                },
            )

            second_response = client.post(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "ANY",
                },
            )

        assert first_response.status_code == 201
        assert second_response.status_code == 404
        assert second_response.json() == {
            "detail": "Possession and parking preference already exists.",
        }


def test_create_customer_requirement_possession_parking_preference_rejects_invalid_possession() -> None:
    """DF-54: Invalid possession values are rejected."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "INVALID",
                    "parking_preference": "ANY",
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_possession_parking_preference_rejects_invalid_parking() -> None:
    """DF-54: Invalid parking values are rejected."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "INVALID",
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_possession_parking_preference_rejects_zero_parking_spaces() -> None:
    """DF-54: Minimum parking spaces must be greater than zero."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "REQUIRED",
                    "parking_spaces_min": 0,
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_possession_parking_preference_rejects_negative_parking_spaces() -> None:
    """DF-54: Negative minimum parking spaces are rejected."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "REQUIRED",
                    "parking_spaces_min": -1,
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_possession_parking_preference_rejects_unknown_fields() -> None:
    """DF-54: Unknown creation fields are rejected."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "ANY",
                    "organization_id": str(organization.id),
                },
            )

        assert response.status_code == 422


def test_create_customer_requirement_possession_parking_preference_returns_404_for_missing_requirement() -> None:
    """DF-54: Preference cannot be created for a missing requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                (
                    f"/api/v1/customer-requirements/{uuid4()}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "ANY",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_create_customer_requirement_possession_parking_preference_prevents_cross_tenant_access() -> None:
    """DF-54: Preference cannot be created for another tenant's requirement."""

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
                (
                    f"/api/v1/customer-requirements/{requirement_b.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "ANY",
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Customer requirement not found.",
        }


def test_create_customer_requirement_possession_parking_preference_requires_update_permission() -> None:
    """DF-54: Creating preferences requires requirements.update."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "ANY",
                    "parking_preference": "ANY",
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_get_customer_requirement_possession_parking_preference_successfully() -> None:
    """DF-54: Retrieve possession and parking preferences."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="WITHIN_6_MONTHS",
            parking_preference="REQUIRED",
            parking_spaces_min=2,
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["id"] == str(preference.id)
        assert payload["organization_id"] == str(organization.id)
        assert payload["customer_requirement_id"] == str(requirement.id)
        assert payload["possession_preference"] == "WITHIN_6_MONTHS"
        assert payload["parking_preference"] == "REQUIRED"
        assert payload["parking_spaces_min"] == 2
        assert payload["is_active"] is True


def test_get_customer_requirement_possession_parking_preference_returns_404_when_missing() -> None:
    """DF-54: GET returns 404 when no preference exists."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": (
                "Customer requirement possession and parking "
                "preference not found."
            ),
        }


def test_get_customer_requirement_possession_parking_preference_returns_404_for_missing_requirement() -> None:
    """DF-54: GET returns 404 for a missing requirement."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                (
                    f"/api/v1/customer-requirements/{uuid4()}"
                    "/possession-parking-preference"
                ),
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": (
                "Customer requirement possession and parking "
                "preference not found."
            ),
        }


def test_get_customer_requirement_possession_parking_preference_prevents_cross_tenant_access() -> None:
    """DF-54: Preference cannot be read from another tenant."""

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

        preference_b = CustomerRequirementPossessionParkingPreference(
            organization_id=organization_b.id,
            customer_requirement_id=requirement_b.id,
            possession_preference="ANY",
            parking_preference="ANY",
            is_active=True,
        )

        db.add(preference_b)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get(
                (
                    f"/api/v1/customer-requirements/{requirement_b.id}"
                    "/possession-parking-preference"
                ),
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": (
                "Customer requirement possession and parking "
                "preference not found."
            ),
        }


def test_get_customer_requirement_possession_parking_preference_requires_read_permission() -> None:
    """DF-54: Reading preferences requires requirements.read."""

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
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_possession_parking_preference_successfully() -> None:
    """DF-54: Update possession, parking, and parking spaces."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            parking_spaces_min=1,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        db.refresh(preference)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "WITHIN_12_MONTHS",
                    "parking_preference": "PREFERRED",
                    "parking_spaces_min": 2,
                    "is_active": False,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["possession_preference"] == "WITHIN_12_MONTHS"
        assert payload["parking_preference"] == "PREFERRED"
        assert payload["parking_spaces_min"] == 2
        assert payload["is_active"] is False


def test_update_customer_requirement_possession_parking_preference_preserves_omitted_fields() -> None:
    """DF-54: Omitted PATCH fields remain unchanged."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            parking_spaces_min=2,
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "is_active": False,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["possession_preference"] == "READY_TO_MOVE"
        assert payload["parking_preference"] == "REQUIRED"
        assert payload["parking_spaces_min"] == 2
        assert payload["is_active"] is False


def test_update_customer_requirement_possession_parking_preference_can_clear_parking_spaces() -> None:
    """DF-54: Explicit null clears the optional parking-space minimum."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            parking_spaces_min=2,
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "parking_spaces_min": None,
                },
            )

        assert response.status_code == 200
        assert response.json()["parking_spaces_min"] is None


def test_update_customer_requirement_possession_parking_preference_rejects_null_possession() -> None:
    """DF-54: Required possession preference cannot be cleared."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": None,
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Possession preference cannot be cleared.",
        }


def test_update_customer_requirement_possession_parking_preference_rejects_null_parking() -> None:
    """DF-54: Required parking preference cannot be cleared."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "parking_preference": None,
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Parking preference cannot be cleared.",
        }


def test_update_customer_requirement_possession_parking_preference_rejects_invalid_parking_spaces() -> None:
    """DF-54: Invalid parking-space minimum is rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            parking_spaces_min=2,
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "parking_spaces_min": 0,
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_possession_parking_preference_rejects_invalid_possession() -> None:
    """DF-54: Invalid PATCH possession values are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "INVALID",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_possession_parking_preference_rejects_invalid_parking() -> None:
    """DF-54: Invalid PATCH parking values are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "parking_preference": "INVALID",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_possession_parking_preference_rejects_unknown_fields() -> None:
    """DF-54: Unknown PATCH fields are rejected."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "unknown_field": "not-allowed",
                },
            )

        assert response.status_code == 422


def test_update_customer_requirement_possession_parking_preference_returns_404_for_missing_preference() -> None:
    """DF-54: Updating a missing preference returns 404."""

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
                    "/possession-parking-preference"
                ),
                json={
                    "parking_spaces_min": 2,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": (
                "Customer requirement possession and parking "
                "preference not found."
            ),
        }


def test_update_customer_requirement_possession_parking_preference_prevents_cross_tenant_access() -> None:
    """DF-54: Preference cannot be updated from another tenant."""

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

        preference_b = CustomerRequirementPossessionParkingPreference(
            organization_id=organization_b.id,
            customer_requirement_id=requirement_b.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            parking_spaces_min=1,
            is_active=True,
        )

        db.add(preference_b)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement_b.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "parking_spaces_min": 2,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": (
                "Customer requirement possession and parking "
                "preference not found."
            ),
        }


def test_update_customer_requirement_possession_parking_preference_requires_update_permission() -> None:
    """DF-54: Updating preferences requires requirements.update."""

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

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            is_active=True,
        )

        db.add(preference)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "parking_spaces_min": 2,
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_customer_requirement_possession_parking_preference_persists_changes() -> None:
    """DF-54: PATCH changes are persisted to the database."""

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        preference = CustomerRequirementPossessionParkingPreference(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            possession_preference="READY_TO_MOVE",
            parking_preference="REQUIRED",
            parking_spaces_min=1,
            is_active=True,
        )

        db.add(preference)
        db.commit()
        preference_id = preference.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                (
                    f"/api/v1/customer-requirements/{requirement.id}"
                    "/possession-parking-preference"
                ),
                json={
                    "possession_preference": "AFTER_12_MONTHS",
                    "parking_preference": "ANY",
                    "parking_spaces_min": 3,
                },
            )

        assert response.status_code == 200

    with TestingSessionLocal() as verification_db:
        persisted_preference = verification_db.scalar(
            select(CustomerRequirementPossessionParkingPreference).where(
                CustomerRequirementPossessionParkingPreference.id
                == preference_id,
                CustomerRequirementPossessionParkingPreference.organization_id
                == organization.id,
                CustomerRequirementPossessionParkingPreference.customer_requirement_id
                == requirement.id,
            )
        )

    assert persisted_preference is not None
    assert persisted_preference.possession_preference == "AFTER_12_MONTHS"
    assert persisted_preference.parking_preference == "ANY"
    assert persisted_preference.parking_spaces_min == 3