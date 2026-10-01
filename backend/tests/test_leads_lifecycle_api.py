"""DF-44 Lead update and lifecycle API tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.leads import router as leads_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditDecision, AuditEvent, AuditEventType
from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session
from app.leads.lifecycle import (
    is_terminal_status,
    is_valid_status_transition,
    validate_status_outcome,
    validate_status_transition,
)
from app.leads.schemas import LeadUpdateRequest


TestingSessionLocal = SessionLocal


# ============================================================================
# Test data helpers
# ============================================================================


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
    """Create a unique global test role."""
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
    permission_key: str,
    is_active: bool = True,
) -> Permission:
    """Return an existing permission or create it."""
    permission = db.scalar(
        select(Permission).where(
            Permission.key == permission_key,
        )
    )

    if permission is None:
        permission = Permission(
            key=permission_key,
            name=permission_key,
            is_active=is_active,
        )
        db.add(permission)
        db.flush()
    else:
        permission.is_active = is_active
        db.flush()

    return permission


def assign_role_to_membership(
    db: Session,
    *,
    membership: Membership,
    role: Role,
) -> MembershipRole:
    """Assign a global role to a tenant membership."""
    assignment = MembershipRole(
        membership_id=membership.id,
        role_id=role.id,
    )
    db.add(assignment)
    db.flush()
    return assignment


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
    permission_key: str = "leads.update",
    organization: Organization | None = None,
    role_is_active: bool = True,
    permission_is_active: bool = True,
    membership_is_active: bool = True,
) -> tuple[User, Organization, Membership, Role, Permission]:
    """Create a user with a tenant permission."""
    organization = organization or create_organization(db)

    user = create_user(db)

    membership = create_membership(
        db,
        user=user,
        organization=organization,
        is_active=membership_is_active,
    )

    role = create_role(
        db,
        is_active=role_is_active,
    )

    permission = get_or_create_permission(
        db,
        permission_key=permission_key,
        is_active=permission_is_active,
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

    db.flush()

    return user, organization, membership, role, permission


def create_contact(
    db: Session,
    *,
    organization: Organization,
    first_name: str = "Test",
    last_name: str = "Contact",
    email: str | None = None,
    phone: str | None = None,
    is_active: bool = True,
) -> Contact:
    """Create a tenant-scoped Contact."""
    contact = Contact(
        organization_id=organization.id,
        first_name=first_name,
        last_name=last_name,
        email=email or f"contact-{uuid4()}@example.com",
        phone=phone,
        is_active=is_active,
    )
    db.add(contact)
    db.flush()
    return contact


def create_lead(
    db: Session,
    *,
    organization: Organization,
    contact: Contact,
    status: str = Lead.STATUS_NEW,
    interest: str | None = None,
    outcome: str | None = None,
    owner_user_id: UUID | None = None,
    next_action: str | None = None,
    next_action_at: datetime | None = None,
    is_active: bool = True,
) -> Lead:
    """Create a tenant-scoped Lead."""
    lead = Lead(
        organization_id=organization.id,
        contact_id=contact.id,
        status=status,
        interest=interest,
        outcome=outcome,
        owner_user_id=owner_user_id,
        next_action=next_action,
        next_action_at=next_action_at,
        is_active=is_active,
    )
    db.add(lead)
    db.flush()
    return lead


def create_test_app(
    *,
    user: User,
) -> FastAPI:
    """
    Create an isolated FastAPI application for Lead API tests.

    Authentication is injected through the repository's existing
    get_current_user_context dependency rather than performing real login.
    """
    test_app = FastAPI()
    test_app.include_router(leads_router)

    def override_get_db_session():
        db = TestingSessionLocal()

        try:
            yield db
        finally:
            db.rollback()
            db.close()

    test_app.dependency_overrides[get_db_session] = override_get_db_session
    test_app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )

    return test_app


@contextmanager
def make_test_client(
    *,
    user: User,
):
    """Create a Lead API TestClient with injected authentication."""
    test_app = create_test_app(user=user)

    with TestClient(test_app) as client:
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


def get_persisted_lead(
    db: Session,
    *,
    organization_id: UUID,
    lead_id: UUID,
) -> Lead | None:
    """Retrieve a Lead using an explicit tenant boundary."""
    return db.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.organization_id == organization_id,
        )
    )


def patch_lead(
    client: TestClient,
    *,
    organization: Organization,
    lead_id: UUID,
    payload: dict,
):
    """PATCH a Lead using the required tenant context."""
    add_tenant_header(client, organization)

    return client.patch(
        f"/api/v1/leads/{lead_id}",
        json=payload,
    )


# ============================================================================
# Lifecycle unit tests
# ============================================================================


def test_terminal_status_detection() -> None:
    assert is_terminal_status(Lead.STATUS_WON) is True
    assert is_terminal_status(Lead.STATUS_LOST) is True
    assert is_terminal_status(Lead.STATUS_NEW) is False
    assert is_terminal_status(Lead.STATUS_NEGOTIATION) is False


def test_same_status_transition_is_allowed() -> None:
    for status in Lead.STATUS_VALUES:
        assert is_valid_status_transition(status, status) is True


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [
        (Lead.STATUS_NEW, Lead.STATUS_CONTACTED),
        (Lead.STATUS_NEW, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_NEW, Lead.STATUS_ON_HOLD),
        (Lead.STATUS_CONTACTED, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_CONTACTED, Lead.STATUS_MATCHING),
        (Lead.STATUS_CONTACTED, Lead.STATUS_ON_HOLD),
        (Lead.STATUS_QUALIFIED, Lead.STATUS_MATCHING),
        (Lead.STATUS_QUALIFIED, Lead.STATUS_VISIT),
        (Lead.STATUS_QUALIFIED, Lead.STATUS_ON_HOLD),
        (Lead.STATUS_MATCHING, Lead.STATUS_VISIT),
        (Lead.STATUS_MATCHING, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_MATCHING, Lead.STATUS_ON_HOLD),
        (Lead.STATUS_VISIT, Lead.STATUS_MATCHING),
        (Lead.STATUS_VISIT, Lead.STATUS_NEGOTIATION),
        (Lead.STATUS_VISIT, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_VISIT, Lead.STATUS_ON_HOLD),
        (Lead.STATUS_NEGOTIATION, Lead.STATUS_WON),
        (Lead.STATUS_NEGOTIATION, Lead.STATUS_LOST),
        (Lead.STATUS_NEGOTIATION, Lead.STATUS_VISIT),
        (Lead.STATUS_NEGOTIATION, Lead.STATUS_ON_HOLD),
        (Lead.STATUS_ON_HOLD, Lead.STATUS_CONTACTED),
        (Lead.STATUS_ON_HOLD, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_ON_HOLD, Lead.STATUS_MATCHING),
        (Lead.STATUS_ON_HOLD, Lead.STATUS_VISIT),
        (Lead.STATUS_ON_HOLD, Lead.STATUS_NEGOTIATION),
    ],
)
def test_allowed_status_transitions(
    current_status: str,
    new_status: str,
) -> None:
    assert is_valid_status_transition(
        current_status,
        new_status,
    ) is True


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [
        (Lead.STATUS_NEW, Lead.STATUS_MATCHING),
        (Lead.STATUS_NEW, Lead.STATUS_VISIT),
        (Lead.STATUS_NEW, Lead.STATUS_NEGOTIATION),
        (Lead.STATUS_NEW, Lead.STATUS_WON),
        (Lead.STATUS_NEW, Lead.STATUS_LOST),
        (Lead.STATUS_CONTACTED, Lead.STATUS_VISIT),
        (Lead.STATUS_CONTACTED, Lead.STATUS_NEGOTIATION),
        (Lead.STATUS_CONTACTED, Lead.STATUS_WON),
        (Lead.STATUS_CONTACTED, Lead.STATUS_LOST),
        (Lead.STATUS_QUALIFIED, Lead.STATUS_NEGOTIATION),
        (Lead.STATUS_QUALIFIED, Lead.STATUS_WON),
        (Lead.STATUS_QUALIFIED, Lead.STATUS_LOST),
        (Lead.STATUS_MATCHING, Lead.STATUS_NEGOTIATION),
        (Lead.STATUS_MATCHING, Lead.STATUS_WON),
        (Lead.STATUS_MATCHING, Lead.STATUS_LOST),
        (Lead.STATUS_VISIT, Lead.STATUS_WON),
        (Lead.STATUS_VISIT, Lead.STATUS_LOST),
        (Lead.STATUS_NEGOTIATION, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_WON, Lead.STATUS_CONTACTED),
        (Lead.STATUS_WON, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_WON, Lead.STATUS_LOST),
        (Lead.STATUS_LOST, Lead.STATUS_CONTACTED),
        (Lead.STATUS_LOST, Lead.STATUS_QUALIFIED),
        (Lead.STATUS_LOST, Lead.STATUS_WON),
    ],
)
def test_invalid_status_transitions(
    current_status: str,
    new_status: str,
) -> None:
    assert is_valid_status_transition(
        current_status,
        new_status,
    ) is False


def test_validate_status_transition_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="Invalid Lead status"):
        validate_status_transition(
            current_status=Lead.STATUS_NEW,
            new_status="INVALID",
        )


def test_won_requires_successful_outcome() -> None:
    validate_status_outcome(
        Lead.STATUS_WON,
        Lead.OUTCOME_SUCCESSFUL,
    )


def test_won_rejects_unsuccessful_outcome() -> None:
    with pytest.raises(ValueError, match="requires outcome"):
        validate_status_outcome(
            Lead.STATUS_WON,
            Lead.OUTCOME_UNSUCCESSFUL,
        )


def test_lost_requires_unsuccessful_outcome() -> None:
    validate_status_outcome(
        Lead.STATUS_LOST,
        Lead.OUTCOME_UNSUCCESSFUL,
    )


def test_lost_rejects_successful_outcome() -> None:
    with pytest.raises(ValueError, match="requires outcome"):
        validate_status_outcome(
            Lead.STATUS_LOST,
            Lead.OUTCOME_SUCCESSFUL,
        )


def test_non_terminal_status_allows_no_outcome() -> None:
    for status in (
        Lead.STATUS_NEW,
        Lead.STATUS_CONTACTED,
        Lead.STATUS_QUALIFIED,
        Lead.STATUS_MATCHING,
        Lead.STATUS_VISIT,
        Lead.STATUS_NEGOTIATION,
        Lead.STATUS_ON_HOLD,
    ):
        validate_status_outcome(status, None)


# ============================================================================
# Schema tests
# ============================================================================


def test_update_schema_accepts_all_editable_fields() -> None:
    owner_id = uuid4()
    timestamp = datetime.now(timezone.utc)

    payload = LeadUpdateRequest(
        status=Lead.STATUS_CONTACTED,
        interest=Lead.INTEREST_HIGH,
        outcome=None,
        owner_user_id=owner_id,
        next_action="Call customer",
        next_action_at=timestamp,
        is_active=True,
    )

    assert payload.status == Lead.STATUS_CONTACTED
    assert payload.interest == Lead.INTEREST_HIGH
    assert payload.owner_user_id == owner_id
    assert payload.next_action == "Call customer"
    assert payload.next_action_at == timestamp
    assert payload.is_active is True


def test_update_schema_allows_empty_patch() -> None:
    payload = LeadUpdateRequest()

    assert payload.model_dump(exclude_unset=True) == {}


# ============================================================================
# API update tests
# ============================================================================


def test_update_lead_status() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEW,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_CONTACTED,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == Lead.STATUS_CONTACTED

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.status == Lead.STATUS_CONTACTED

    finally:
        db.rollback()
        db.close()


def test_update_lead_interest() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "interest": Lead.INTEREST_HIGH,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["interest"] == Lead.INTEREST_HIGH

    finally:
        db.rollback()
        db.close()


def test_update_lead_outcome() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "outcome": Lead.OUTCOME_SUCCESSFUL,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == Lead.OUTCOME_SUCCESSFUL

    finally:
        db.rollback()
        db.close()


def test_update_next_action_and_time() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        next_action_at = datetime.now(timezone.utc) + timedelta(days=1)

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": "Call customer",
                    "next_action_at": next_action_at.isoformat(),
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["next_action"] == "Call customer"
        assert body["next_action_at"] is not None

    finally:
        db.rollback()
        db.close()


def test_update_is_active() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "is_active": False,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is False

    finally:
        db.rollback()
        db.close()


# ============================================================================
# Lifecycle API validation
# ============================================================================


def test_invalid_transition_returns_400() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEW,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_WON,
                    "outcome": Lead.OUTCOME_SUCCESSFUL,
                },
            )

        assert response.status_code == 400, response.text
        assert "transition" in response.json()["detail"].lower()

    finally:
        db.rollback()
        db.close()


def test_won_without_successful_outcome_returns_400() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_WON,
                },
            )

        assert response.status_code == 400, response.text
        assert "SUCCESSFUL" in response.json()["detail"]

    finally:
        db.rollback()
        db.close()


def test_won_with_successful_outcome_succeeds() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_WON,
                    "outcome": Lead.OUTCOME_SUCCESSFUL,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["status"] == Lead.STATUS_WON
        assert body["outcome"] == Lead.OUTCOME_SUCCESSFUL

    finally:
        db.rollback()
        db.close()


def test_lost_without_unsuccessful_outcome_returns_400() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_LOST,
                },
            )

        assert response.status_code == 400, response.text
        assert "UNSUCCESSFUL" in response.json()["detail"]

    finally:
        db.rollback()
        db.close()


def test_lost_with_unsuccessful_outcome_succeeds() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_LOST,
                    "outcome": Lead.OUTCOME_UNSUCCESSFUL,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["status"] == Lead.STATUS_LOST
        assert body["outcome"] == Lead.OUTCOME_UNSUCCESSFUL

    finally:
        db.rollback()
        db.close()


def test_terminal_won_lead_cannot_change_status() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_WON,
            outcome=Lead.OUTCOME_SUCCESSFUL,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_CONTACTED,
                },
            )

        assert response.status_code == 400, response.text

    finally:
        db.rollback()
        db.close()


def test_terminal_lost_lead_cannot_change_status() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_LOST,
            outcome=Lead.OUTCOME_UNSUCCESSFUL,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_CONTACTED,
                },
            )

        assert response.status_code == 400, response.text

    finally:
        db.rollback()
        db.close()


def test_on_hold_is_reversible() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_CONTACTED,
        )

        db.commit()

        with make_test_client(user=user) as client:
            first_response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_ON_HOLD,
                },
            )

            assert first_response.status_code == 200, first_response.text

            second_response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_QUALIFIED,
                },
            )

        assert second_response.status_code == 200, second_response.text
        assert second_response.json()["status"] == Lead.STATUS_QUALIFIED

    finally:
        db.rollback()
        db.close()


# ============================================================================
# Owner management
# ============================================================================


def test_assign_owner_to_active_same_tenant_member() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
            is_active=True,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "owner_user_id": str(owner.id),
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["owner_user_id"] == str(owner.id)

    finally:
        db.rollback()
        db.close()


def test_clear_owner() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            owner_user_id=owner.id,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "owner_user_id": None,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["owner_user_id"] is None

    finally:
        db.rollback()
        db.close()


def test_owner_must_belong_to_same_tenant() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        other_organization = create_organization(db)
        other_user = create_user(db)

        create_membership(
            db,
            user=other_user,
            organization=other_organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "owner_user_id": str(other_user.id),
                },
            )

        assert response.status_code == 400, response.text
        assert "organization" in response.json()["detail"].lower()

    finally:
        db.rollback()
        db.close()


def test_owner_must_have_active_membership() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
            is_active=False,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "owner_user_id": str(owner.id),
                },
            )

        assert response.status_code == 400, response.text

    finally:
        db.rollback()
        db.close()


# ============================================================================
# Tenant and authorization security
# ============================================================================


def test_cross_tenant_lead_returns_404() -> None:
    db = TestingSessionLocal()

    try:
        user, organization_a, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        organization_b = create_organization(db)

        contact_b = create_contact(
            db,
            organization=organization_b,
        )

        lead_b = create_lead(
            db,
            organization=organization_b,
            contact=contact_b,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization_a,
                lead_id=lead_b.id,
                payload={
                    "interest": Lead.INTEREST_HIGH,
                },
            )

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Lead not found."

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization_b.id,
            lead_id=lead_b.id,
        )

        assert persisted is not None
        assert persisted.interest is None

    finally:
        db.rollback()
        db.close()


def test_missing_lead_returns_404() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=uuid4(),
                payload={
                    "interest": Lead.INTEREST_HIGH,
                },
            )

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Lead not found."

    finally:
        db.rollback()
        db.close()


def test_missing_organization_context_returns_400() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = client.patch(
                f"/api/v1/leads/{lead.id}",
                json={
                    "interest": Lead.INTEREST_HIGH,
                },
            )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Organization context is required."

    finally:
        db.rollback()
        db.close()


def test_permission_is_required() -> None:
    db = TestingSessionLocal()

    try:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "interest": Lead.INTEREST_HIGH,
                },
            )

        assert response.status_code == 403, response.text
        assert response.json()["detail"] == "Permission denied."

    finally:
        db.rollback()
        db.close()


def test_denied_authorization_is_audited() -> None:
    db = TestingSessionLocal()

    try:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "interest": Lead.INTEREST_HIGH,
                },
            )

        assert response.status_code == 403, response.text

        db.expire_all()

        audit_event = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.user_id == user.id,
                AuditEvent.organization_id == organization.id,
                AuditEvent.event_type == AuditEventType.AUTHORIZATION,
                AuditEvent.decision == AuditDecision.DENIED,
                AuditEvent.permission_key == "leads.update",
            )
            .order_by(AuditEvent.occurred_at.desc())
        )

        assert audit_event is not None
        assert audit_event.user_id == user.id
        assert audit_event.organization_id == organization.id
        assert audit_event.event_type == AuditEventType.AUTHORIZATION
        assert audit_event.decision == AuditDecision.DENIED
        assert audit_event.permission_key == "leads.update"

    finally:
        db.rollback()
        db.close()


# ============================================================================
# PATCH semantics
# ============================================================================


def test_empty_patch_is_noop() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_CONTACTED,
            interest=Lead.INTEREST_MEDIUM,
            next_action="Existing action",
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={},
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["status"] == Lead.STATUS_CONTACTED
        assert body["interest"] == Lead.INTEREST_MEDIUM
        assert body["next_action"] == "Existing action"

    finally:
        db.rollback()
        db.close()


def test_next_action_can_be_cleared() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": None,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["next_action"] is None

    finally:
        db.rollback()
        db.close()


def test_next_action_at_can_be_cleared() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action_at": None,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["next_action_at"] is None

    finally:
        db.rollback()
        db.close()


def test_interest_can_be_cleared() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            interest=Lead.INTEREST_HIGH,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "interest": None,
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["interest"] is None

    finally:
        db.rollback()
        db.close()


def test_is_active_cannot_be_null() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "is_active": None,
                },
            )

        assert response.status_code == 400, response.text
        assert "is_active" in response.json()["detail"]

    finally:
        db.rollback()
        db.close()


# ============================================================================
# Schema validation
# ============================================================================


def test_invalid_status_is_rejected_by_schema() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": "INVALID",
                },
            )

        assert response.status_code == 422, response.text

    finally:
        db.rollback()
        db.close()


def test_invalid_interest_is_rejected_by_schema() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "interest": "INVALID",
                },
            )

        assert response.status_code == 422, response.text

    finally:
        db.rollback()
        db.close()


def test_invalid_outcome_is_rejected_by_schema() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "outcome": "INVALID",
                },
            )

        assert response.status_code == 422, response.text

    finally:
        db.rollback()
        db.close()


def test_next_action_max_length_is_enforced() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": "x" * 501,
                },
            )

        assert response.status_code == 422, response.text

    finally:
        db.rollback()
        db.close()


# ============================================================================
# Role model regression
# ============================================================================


def test_role_is_global_and_tenant_assignment_is_membership_scoped() -> None:
    db = TestingSessionLocal()

    try:
        organization_a = create_organization(db)
        organization_b = create_organization(db)

        user_a = create_user(db)
        user_b = create_user(db)

        membership_a = create_membership(
            db,
            user=user_a,
            organization=organization_a,
        )

        membership_b = create_membership(
            db,
            user=user_b,
            organization=organization_b,
        )

        role = create_role(
            db,
            name=f"Global Test Role-{uuid4()}",
        )

        assignment_a = assign_role_to_membership(
            db,
            membership=membership_a,
            role=role,
        )

        assignment_b = assign_role_to_membership(
            db,
            membership=membership_b,
            role=role,
        )

        db.commit()

        assert role.id is not None
        assert not hasattr(role, "organization_id")

        assert assignment_a.role_id == role.id
        assert assignment_b.role_id == role.id

        assert assignment_a.membership_id == membership_a.id
        assert assignment_b.membership_id == membership_b.id

    finally:
        db.rollback()
        db.close()

def test_reassign_owner_to_another_active_same_tenant_member() -> None:
    db = TestingSessionLocal()

    try:
        organization = create_organization(db)
        user = create_user(db)
        owner_a = create_user(db)
        owner_b = create_user(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )
        create_membership(
            db,
            user=owner_a,
            organization=organization,
        )
        create_membership(
            db,
            user=owner_b,
            organization=organization,
        )

        role = create_role(db)
        assign_role_to_membership(
            db,
            membership=membership,
            role=role,
        )

        permission = get_or_create_permission(
            db,
            permission_key="leads.update",
        )
        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            owner_user_id=owner_a.id,
        )

        db.commit()

        test_app = create_test_app(user=user)

        with TestClient(test_app) as client:
            response = client.patch(
                f"/api/v1/leads/{lead.id}",
                headers={
                    "X-Organization-ID": str(organization.id),
                },
                json={
                    "owner_user_id": str(owner_b.id),
                },
            )

        assert response.status_code == 200
        assert response.json()["owner_user_id"] == str(owner_b.id)

        db.expire_all()

        refreshed_lead = db.get(Lead, lead.id)

        assert refreshed_lead is not None
        assert refreshed_lead.owner_user_id == owner_b.id
        assert refreshed_lead.owner_user_id != owner_a.id

    finally:
        db.rollback()
        db.close()


def test_invalid_owner_reassignment_preserves_existing_owner() -> None:
    db = TestingSessionLocal()

    try:
        organization = create_organization(db)
        other_organization = create_organization(db)

        user = create_user(db)
        current_owner = create_user(db)
        invalid_owner = create_user(db)

        membership = create_membership(
            db,
            user=user,
            organization=organization,
        )
        create_membership(
            db,
            user=current_owner,
            organization=organization,
        )
        create_membership(
            db,
            user=invalid_owner,
            organization=other_organization,
        )

        role = create_role(db)
        assign_role_to_membership(
            db,
            membership=membership,
            role=role,
        )

        permission = get_or_create_permission(
            db,
            permission_key="leads.update",
        )
        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            owner_user_id=current_owner.id,
        )

        db.commit()

        test_app = create_test_app(user=user)

        with TestClient(test_app) as client:
            response = client.patch(
                f"/api/v1/leads/{lead.id}",
                headers={
                    "X-Organization-ID": str(organization.id),
                },
                json={
                    "owner_user_id": str(invalid_owner.id),
                },
            )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Lead owner must belong to the organization."
        )

        db.expire_all()

        refreshed_lead = db.get(Lead, lead.id)

        assert refreshed_lead is not None
        assert refreshed_lead.owner_user_id == current_owner.id

    finally:
        db.rollback()
        db.close()


def test_owner_can_be_member_of_multiple_organizations() -> None:
    db = TestingSessionLocal()

    try:
        organization_a = create_organization(db)
        organization_b = create_organization(db)

        actor = create_user(db)
        owner = create_user(db)

        actor_membership = create_membership(
            db,
            user=actor,
            organization=organization_a,
        )
        create_membership(
            db,
            user=owner,
            organization=organization_a,
        )
        create_membership(
            db,
            user=owner,
            organization=organization_b,
        )

        role = create_role(db)
        assign_role_to_membership(
            db,
            membership=actor_membership,
            role=role,
        )

        permission = get_or_create_permission(
            db,
            permission_key="leads.update",
        )
        assign_permission_to_role(
            db,
            role=role,
            permission=permission,
        )

        contact = create_contact(
            db,
            organization=organization_a,
        )

        lead = create_lead(
            db,
            organization=organization_a,
            contact=contact,
        )

        db.commit()

        test_app = create_test_app(user=actor)

        with TestClient(test_app) as client:
            response = client.patch(
                f"/api/v1/leads/{lead.id}",
                headers={
                    "X-Organization-ID": str(organization_a.id),
                },
                json={
                    "owner_user_id": str(owner.id),
                },
            )

        assert response.status_code == 200
        assert response.json()["owner_user_id"] == str(owner.id)

        db.expire_all()

        refreshed_lead = db.get(Lead, lead.id)

        assert refreshed_lead is not None
        assert refreshed_lead.organization_id == organization_a.id
        assert refreshed_lead.owner_user_id == owner.id

    finally:
        db.rollback()
        db.close()

def test_update_next_action_preserves_existing_next_action_at() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        existing_next_action_at = datetime.now(timezone.utc) + timedelta(days=2)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Existing action",
            next_action_at=existing_next_action_at,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": "Updated action",
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["next_action"] == "Updated action"
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.next_action == "Updated action"
        assert persisted.next_action_at is not None
        assert persisted.next_action_at == existing_next_action_at

    finally:
        db.rollback()
        db.close()


def test_update_next_action_at_preserves_existing_next_action() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        existing_next_action_at = datetime.now(timezone.utc) + timedelta(days=1)
        updated_next_action_at = datetime.now(timezone.utc) + timedelta(days=3)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Existing action",
            next_action_at=existing_next_action_at,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action_at": updated_next_action_at.isoformat(),
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["next_action"] == "Existing action"
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.next_action == "Existing action"
        assert persisted.next_action_at is not None
        assert persisted.next_action_at != existing_next_action_at

    finally:
        db.rollback()
        db.close()


def test_clear_next_action_preserves_existing_next_action_at() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        existing_next_action_at = datetime.now(timezone.utc) + timedelta(days=2)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
            next_action_at=existing_next_action_at,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": None,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["next_action"] is None
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.next_action is None
        assert persisted.next_action_at is not None
        assert persisted.next_action_at == existing_next_action_at

    finally:
        db.rollback()
        db.close()


def test_clear_next_action_at_preserves_existing_next_action() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
            next_action_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action_at": None,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["next_action"] == "Call customer"
        assert body["next_action_at"] is None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.next_action == "Call customer"
        assert persisted.next_action_at is None

    finally:
        db.rollback()
        db.close()


def test_update_outcome_preserves_next_action_fields() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        existing_next_action_at = datetime.now(timezone.utc) + timedelta(days=2)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
            next_action="Follow up on negotiation",
            next_action_at=existing_next_action_at,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "outcome": Lead.OUTCOME_SUCCESSFUL,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["outcome"] == Lead.OUTCOME_SUCCESSFUL
        assert body["next_action"] == "Follow up on negotiation"
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.outcome == Lead.OUTCOME_SUCCESSFUL
        assert persisted.next_action == "Follow up on negotiation"
        assert persisted.next_action_at == existing_next_action_at

    finally:
        db.rollback()
        db.close()


def test_update_next_action_fields_preserves_existing_outcome() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEGOTIATION,
            outcome=Lead.OUTCOME_SUCCESSFUL,
        )

        db.commit()

        next_action_at = datetime.now(timezone.utc) + timedelta(days=2)

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": "Schedule final discussion",
                    "next_action_at": next_action_at.isoformat(),
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["outcome"] == Lead.OUTCOME_SUCCESSFUL
        assert body["next_action"] == "Schedule final discussion"
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.outcome == Lead.OUTCOME_SUCCESSFUL
        assert persisted.next_action == "Schedule final discussion"
        assert persisted.next_action_at is not None

    finally:
        db.rollback()
        db.close()


def test_deactivating_lead_preserves_operational_fields() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        next_action_at = datetime.now(timezone.utc) + timedelta(days=2)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_CONTACTED,
            outcome=Lead.OUTCOME_SUCCESSFUL,
            next_action="Follow up with customer",
            next_action_at=next_action_at,
            is_active=True,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "is_active": False,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["is_active"] is False
        assert body["outcome"] == Lead.OUTCOME_SUCCESSFUL
        assert body["next_action"] == "Follow up with customer"
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.is_active is False
        assert persisted.outcome == Lead.OUTCOME_SUCCESSFUL
        assert persisted.next_action == "Follow up with customer"
        assert persisted.next_action_at == next_action_at

    finally:
        db.rollback()
        db.close()


def test_reactivating_lead_preserves_operational_fields() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )

        contact = create_contact(
            db,
            organization=organization,
        )

        next_action_at = datetime.now(timezone.utc) + timedelta(days=3)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_CONTACTED,
            outcome=Lead.OUTCOME_UNSUCCESSFUL,
            next_action="Review alternative properties",
            next_action_at=next_action_at,
            is_active=False,
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "is_active": True,
                },
            )

        assert response.status_code == 200, response.text

        body = response.json()

        assert body["is_active"] is True
        assert body["outcome"] == Lead.OUTCOME_UNSUCCESSFUL
        assert body["next_action"] == "Review alternative properties"
        assert body["next_action_at"] is not None

        db.expire_all()

        persisted = get_persisted_lead(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert persisted is not None
        assert persisted.is_active is True
        assert persisted.outcome == Lead.OUTCOME_UNSUCCESSFUL
        assert persisted.next_action == "Review alternative properties"
        assert persisted.next_action_at == next_action_at

    finally:
        db.rollback()
        db.close()