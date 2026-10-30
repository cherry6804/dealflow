"""Integration tests for team membership and invitation APIs."""

from __future__ import annotations
from app.db.models.organization import Organization
from collections.abc import Iterator
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import team as team_api
from app.api.team import router as team_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.audit_event import AuditEvent
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.role import Role
from app.db.models.team_invitation import TeamInvitation
from app.db.session import SessionLocal, get_db_session
from app.team.service import hash_invitation_token
from tests.test_deals_api import (
    create_authorized_user,
    create_membership,
    create_user,
)

TestingSessionLocal = SessionLocal
BASE_URL = "/api/v1/team"


def create_team_test_app(*, user) -> FastAPI:
    """Build an isolated FastAPI app using the existing test database."""
    app = FastAPI()
    app.include_router(team_router)

    def override_get_db_session() -> Iterator[Session]:
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



def create_role(
    db: Session,
    *,
    organization_id: UUID | None = None,
    name: str | None = None,
    is_active: bool = True,
) -> Role:
    """Create a role, scoped to an organization when provided."""
    role = Role(
        name=name or f"Test Role-{uuid4()}",
        organization_id=organization_id,
        is_active=is_active,
    )
    db.add(role)
    db.flush()
    return role



def attach_role(
    db: Session,
    *,
    membership: Membership,
    role: Role,
) -> None:
    db.add(
        MembershipRole(
            membership_id=membership.id,
            role_id=role.id,
        )
    )
    db.flush()

def create_manager(*, permissions: tuple[str, ...]):
    """Create a test user and organization with loaded, detached attributes."""
    db = TestingSessionLocal()
    try:
        user, organization = create_authorized_user(
            db,
            permission_keys=permissions,
        )

        # The helper commits, which expires ORM attributes by default.
        # Refresh before detaching so later test setup can safely use IDs
        # and the API dependency can read the user's attributes.
        db.refresh(user)
        db.refresh(organization)

        db.expunge(user)
        db.expunge(organization)

        return user, organization
    finally:
        db.close()

def create_invitation(
    client: TestClient,
    *,
    email: str,
    role_id: UUID,
):
    response = client.post(
        f"{BASE_URL}/invitations",
        json={"email": email, "role_id": str(role_id)},
    )
    return response


def test_list_team_members_requires_permission() -> None:
    user, organization = create_manager(permissions=("deals.read",))

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        response = client.get(f"{BASE_URL}/members")

    assert response.status_code == 403, response.text

def test_list_team_members_returns_active_members() -> None:
    user, organization = create_manager(
        permissions=("organization.members.read",)
    )

    with TestingSessionLocal() as db:
        inactive_user = create_user(db)
        inactive_user_id = inactive_user.id

        create_membership(
            db,
            user=inactive_user,
            organization=organization,
            is_active=False,
        )
        db.commit()

    app = create_team_test_app(user=user)

    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        response = client.get(f"{BASE_URL}/members")

    assert response.status_code == 200, response.text

    members = response.json()

    assert any(
        item["user_id"] == str(user.id)
        for item in members
    )
    assert all(
        item["user_id"] != str(inactive_user_id)
        for item in members
    )


def test_create_invitation_queues_email_and_does_not_expose_token(
    monkeypatch,
) -> None:
    user, organization = create_manager(
        permissions=("organization.invites.manage",)
    )

    with TestingSessionLocal() as db:
        role = create_role(db, organization_id=organization.id)
        role_id = role.id
        db.commit()

    queued: list[dict[str, str]] = []

    def fake_enqueue(db, *, recipient: str, token: str):
        queued.append({"recipient": recipient, "token": token})
        return None

    monkeypatch.setattr(
        team_api,
        "enqueue_team_invitation_email",
        fake_enqueue,
    )

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        response = create_invitation(
            client,
            email="new.member@example.com",
            role_id=role_id,
        )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["organization_id"] == str(organization.id)
    assert result["email"] == "new.member@example.com"
    assert result["role_id"] == str(role_id)
    assert result["status"] == "pending"
    assert "token" not in result
    assert len(queued) == 1
    assert queued[0]["recipient"] == "new.member@example.com"
    assert len(queued[0]["token"]) >= 32

    with TestingSessionLocal() as db:
        persisted = db.get(TeamInvitation, UUID(result["id"]))
        assert persisted is not None
        assert persisted.token_hash == hash_invitation_token(
            queued[0]["token"]
        )
        assert persisted.token_hash != queued[0]["token"]


def test_duplicate_pending_invitation_is_rejected(monkeypatch) -> None:
    user, organization = create_manager(
        permissions=("organization.invites.manage",)
    )

    with TestingSessionLocal() as db:
        role = create_role(db, organization_id=organization.id)
        role_id = role.id
        db.commit()

    monkeypatch.setattr(
        team_api,
        "enqueue_team_invitation_email",
        lambda *args, **kwargs: None,
    )

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )

        first = create_invitation(
            client,
            email="duplicate@example.com",
            role_id=role_id,
        )
        second = create_invitation(
            client,
            email="duplicate@example.com",
            role_id=role_id,
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


def test_invitation_list_is_scoped_to_organization(monkeypatch) -> None:
    user_a, organization_a = create_manager(
        permissions=("organization.invites.manage",)
    )
    user_b, organization_b = create_manager(
        permissions=("organization.invites.manage",)
    )

    with TestingSessionLocal() as db:
        role = create_role(db, organization_id=organization_b.id)
        role_id = role.id
        db.commit()

    monkeypatch.setattr(
        team_api,
        "enqueue_team_invitation_email",
        lambda *args, **kwargs: None,
    )

    app_b = create_team_test_app(user=user_b)
    with TestClient(app_b) as client_b:
        client_b.headers.update(
            {"X-Organization-ID": str(organization_b.id)}
        )
        created = create_invitation(
            client_b,
            email="tenant-b@example.com",
            role_id=role_id,
        )
    assert created.status_code == 201, created.text

    app_a = create_team_test_app(user=user_a)
    with TestClient(app_a) as client_a:
        client_a.headers.update(
            {"X-Organization-ID": str(organization_a.id)}
        )
        response = client_a.get(f"{BASE_URL}/invitations")

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_revoke_invitation_and_reject_second_revocation(
    monkeypatch,
) -> None:
    user, organization = create_manager(
        permissions=("organization.invites.manage",)
    )

    with TestingSessionLocal() as db:
        role = create_role(db, organization_id=organization.id)
        role_id = role.id
        db.commit()

    monkeypatch.setattr(
        team_api,
        "enqueue_team_invitation_email",
        lambda *args, **kwargs: None,
    )

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        created = create_invitation(
            client,
            email="revoke@example.com",
            role_id=role_id,
        )
        assert created.status_code == 201, created.text

        invitation_id = created.json()["id"]
        revoked = client.post(
            f"{BASE_URL}/invitations/{invitation_id}/revoke"
        )
        again = client.post(
            f"{BASE_URL}/invitations/{invitation_id}/revoke"
        )

    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
    assert again.status_code == 409, again.text


def test_resend_invitation_rotates_token(monkeypatch) -> None:
    user, organization = create_manager(
        permissions=("organization.invites.manage",)
    )

    with TestingSessionLocal() as db:
        role = create_role(db, organization_id=organization.id)
        role_id = role.id
        db.commit()

    queued: list[str] = []

    def fake_enqueue(db, *, recipient: str, token: str):
        queued.append(token)
        return None

    monkeypatch.setattr(
        team_api,
        "enqueue_team_invitation_email",
        fake_enqueue,
    )

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        created = create_invitation(
            client,
            email="resend@example.com",
            role_id=role_id,
        )
        assert created.status_code == 201, created.text

        invitation_id = created.json()["id"]
        resent = client.post(
            f"{BASE_URL}/invitations/{invitation_id}/resend"
        )

    assert resent.status_code == 200, resent.text
    assert resent.json()["status"] == "pending"
    assert len(queued) == 2
    assert queued[0] != queued[1]

    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, UUID(invitation_id))
        assert invitation is not None
        assert invitation.token_hash == hash_invitation_token(queued[1])
        assert invitation.token_hash != hash_invitation_token(queued[0])


def test_update_member_role_and_remove_member() -> None:
    manager, organization = create_manager(
        permissions=(
            "organization.members.manage",
            "organization.members.read",
        )
    )

    with TestingSessionLocal() as db:
        target_user = create_user(db)
        target_membership = create_membership(
            db,
            user=target_user,
            organization=organization,
        )
        role = create_role(db, organization_id=organization.id)
        membership_id = target_membership.id
        role_id = role.id
        db.commit()

    app = create_team_test_app(user=manager)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )

        updated = client.put(
            f"{BASE_URL}/members/{membership_id}/role",
            json={"role_id": str(role_id)},
        )
        removed = client.post(
            f"{BASE_URL}/members/{membership_id}/remove",
            json={"reason": "Left the team"},
        )

    assert updated.status_code == 200, updated.text
    assert removed.status_code == 200, removed.text
    assert removed.json()["membership_id"] == str(membership_id)
    assert removed.json()["is_active"] is False

    with TestingSessionLocal() as db:
        persisted = db.get(Membership, membership_id)
        assert persisted is not None
        assert persisted.is_active is False
        assignments = db.scalars(
            select(MembershipRole).where(
                MembershipRole.membership_id == membership_id
            )
        ).all()
        assert len(assignments) == 1
        assert assignments[0].role_id == role_id


def test_member_management_requires_permission() -> None:
    manager, organization = create_manager(
        permissions=("deals.read",)
    )

    with TestingSessionLocal() as db:
        target_user = create_user(db)
        target_membership = create_membership(
            db,
            user=target_user,
            organization=organization,
        )
        role = create_role(db, organization_id=organization.id)
        membership_id = target_membership.id
        role_id = role.id
        db.commit()

    app = create_team_test_app(user=manager)
    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        update_response = client.put(
            f"{BASE_URL}/members/{membership_id}/role",
            json={"role_id": str(role_id)},
        )
        remove_response = client.post(
            f"{BASE_URL}/members/{membership_id}/remove",
            json={"reason": "Left the team"},
        )

    assert update_response.status_code == 403, update_response.text
    assert remove_response.status_code == 403, remove_response.text


def test_custom_role_crud_returns_tenant_and_audits_changes() -> None:
    actor, organization = create_manager(
        permissions=("organization.roles.manage",)
    )
    app = create_team_test_app(user=actor)

    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        created = client.post(
            f"{BASE_URL}/roles",
            json={
                "name": "Sales Reviewer",
                "description": "Read sales records",
                "permission_keys": ["leads.read"],
            },
        )

        assert created.status_code == 201, created.text
        created_payload = created.json()
        assert created_payload["organization_id"] == str(organization.id)
        assert created_payload["permission_keys"] == ["leads.read"]
        role_id = created_payload["id"]

        duplicate = client.post(
            f"{BASE_URL}/roles",
            json={"name": "sales reviewer", "permission_keys": []},
        )
        assert duplicate.status_code == 409, duplicate.text

        updated = client.put(
            f"{BASE_URL}/roles/{role_id}",
            json={
                "name": "Sales Reviewer Updated",
                "permission_keys": ["leads.read", "leads.update"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["organization_id"] == str(organization.id)
        assert updated.json()["permission_keys"] == [
            "leads.read",
            "leads.update",
        ]

        deactivated = client.post(f"{BASE_URL}/roles/{role_id}/deactivate")
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["is_active"] is False
        assert deactivated.json()["organization_id"] == str(organization.id)

    with TestingSessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.user_id == actor.id,
                AuditEvent.organization_id == organization.id,
                AuditEvent.resource_type == "role",
                AuditEvent.resource_id == role_id,
            )
        ).all()
        assert {event.action for event in events} >= {
            "organization.roles.created",
            "organization.roles.updated",
            "organization.roles.deactivated",
        }


def test_custom_role_cannot_grant_owner_only_permissions() -> None:
    actor, organization = create_manager(
        permissions=("organization.roles.manage",)
    )
    app = create_team_test_app(user=actor)

    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        responses = [
            client.post(
                f"{BASE_URL}/roles",
                json={
                    "name": f"Privilege Escalation Attempt {index}",
                    "permission_keys": [permission_key],
                },
            )
            for index, permission_key in enumerate(
                (
                    "organization.roles.manage",
                    "billing.audit.read",
                    "organization.members.manage",
                    "organization.invites.manage",
                )
            )
        ]

    assert [response.status_code for response in responses] == [
        403,
        403,
        403,
        403,
    ]
