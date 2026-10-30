"""Integration tests for invitation-based signup and acceptance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import invitation_signup as signup_api
from app.api import team as team_api
from app.api.invitation_signup import router as signup_router
from app.db.models.membership import Membership
from app.db.models.team_invitation import TeamInvitation
from app.db.models.user import User
from app.db.session import get_db_session
from app.team.service import hash_invitation_token
from tests.test_deals_api import create_user
from tests.test_team_api import (
    TestingSessionLocal,
    create_invitation,
    create_manager,
    create_role,
    create_team_test_app,
)

SIGNUP_URL = "/api/v1/auth/signup-invitation"
TEAM_ACCEPT_URL = "/api/v1/team/invitations/accept"


def unique_email(prefix: str) -> str:
    """Return an email address unique across repeated test runs."""
    return f"{prefix}-{uuid4().hex}@example.com"


def create_signup_test_app() -> FastAPI:
    """Build an isolated app for public invitation signup."""
    app = FastAPI()
    app.include_router(signup_router)

    def override_get_db_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return app


def create_pending_invitation(
    monkeypatch,
    *,
    email: str,
) -> tuple[UUID, str]:
    """Create an organization-scoped invitation and return its raw token."""
    user, organization = create_manager(permissions=("organization.invites.manage",))

    with TestingSessionLocal() as db:
        role = create_role(
            db,
            organization_id=organization.id,
        )
        role_id = role.id
        db.commit()

    queued_tokens: list[str] = []

    def fake_enqueue(db, *, recipient: str, token: str):
        assert recipient == email
        queued_tokens.append(token)

    monkeypatch.setattr(
        team_api,
        "enqueue_team_invitation_email",
        fake_enqueue,
    )

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = create_invitation(
            client,
            email=email,
            role_id=role_id,
        )

    assert response.status_code == 201, response.text
    assert len(queued_tokens) == 1

    return UUID(response.json()["id"]), queued_tokens[0]


def signup_payload(*, email: str, token: str) -> dict[str, str]:
    return {
        "display_name": "Invitation Test User",
        "email": email,
        "password": "A-Strong-Test-Password-123!",
        "invitation_token": token,
    }


def stub_verification_email(monkeypatch) -> None:
    """Avoid sending email while testing signup persistence."""
    monkeypatch.setattr(
        signup_api,
        "create_verification_token",
        lambda db, *, user, now: (None, "test-verification-token"),
    )
    monkeypatch.setattr(
        signup_api,
        "enqueue_verification_email",
        lambda db, *, recipient, token, now: None,
    )


def create_existing_user(
    *,
    email: str,
    verified: bool = False,
) -> User:
    """Persist a test user with a known email and verification state."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        user.email = email
        user.is_email_verified = verified
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def test_invitation_signup_creates_unverified_account(monkeypatch) -> None:
    email = unique_email("invite-signup-success")
    _, token = create_pending_invitation(monkeypatch, email=email)
    stub_verification_email(monkeypatch)

    app = create_signup_test_app()
    with TestClient(app) as client:
        response = client.post(
            SIGNUP_URL,
            json=signup_payload(email=email, token=token),
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == email
    assert body["user"]["display_name"] == "Invitation Test User"
    assert body["verification_required"] is True

    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.is_active is True
        assert user.is_email_verified is False


def test_invitation_signup_rejects_email_mismatch(monkeypatch) -> None:
    invited_email = unique_email("invited-person")
    different_email = unique_email("different-person")

    _, token = create_pending_invitation(
        monkeypatch,
        email=invited_email,
    )
    stub_verification_email(monkeypatch)

    app = create_signup_test_app()
    with TestClient(app) as client:
        response = client.post(
            SIGNUP_URL,
            json=signup_payload(
                email=different_email,
                token=token,
            ),
        )

    assert response.status_code == 403, response.text

    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == different_email))
        assert user is None


def test_invitation_signup_marks_expired_invitation(monkeypatch) -> None:
    email = unique_email("expired-invite-signup")
    invitation_id, token = create_pending_invitation(
        monkeypatch,
        email=email,
    )
    stub_verification_email(monkeypatch)

    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()

    app = create_signup_test_app()
    with TestClient(app) as client:
        response = client.post(
            SIGNUP_URL,
            json=signup_payload(email=email, token=token),
        )

    assert response.status_code == 410, response.text

    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        assert invitation.status == "expired"

        user = db.scalar(select(User).where(User.email == email))
        assert user is None


def test_invitation_signup_rejects_existing_account(monkeypatch) -> None:
    email = unique_email("existing-invite-user")
    create_existing_user(email=email)

    _, token = create_pending_invitation(monkeypatch, email=email)
    stub_verification_email(monkeypatch)

    app = create_signup_test_app()
    with TestClient(app) as client:
        response = client.post(
            SIGNUP_URL,
            json=signup_payload(email=email, token=token),
        )

    assert response.status_code == 409, response.text

    with TestingSessionLocal() as db:
        users = db.scalars(select(User).where(User.email == email)).all()
        assert len(users) == 1


def test_legacy_invitation_signup_is_disabled_in_production(monkeypatch) -> None:
    settings = signup_api.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(signup_api, "get_settings", lambda: settings)
    app = create_signup_test_app()

    with TestClient(app) as client:
        response = client.post(
            SIGNUP_URL,
            json=signup_payload(
                email=unique_email("legacy-production"),
                token="x" * 40,
            ),
        )

    assert response.status_code == 410
    assert "through SIBVO" in response.json()["detail"]


def test_unverified_user_cannot_accept_invitation(monkeypatch) -> None:
    email = unique_email("unverified-invite-accept")

    _, token = create_pending_invitation(monkeypatch, email=email)
    user = create_existing_user(email=email, verified=False)

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        response = client.post(
            TEAM_ACCEPT_URL,
            json={"token": token},
        )

    assert response.status_code == 403, response.text
    assert "Verify your email" in response.json()["detail"]

    with TestingSessionLocal() as db:
        invitation = db.scalar(
            select(TeamInvitation).where(
                TeamInvitation.token_hash == hash_invitation_token(token)
            )
        )
        assert invitation is not None
        assert invitation.status == "pending"


def test_verified_user_can_accept_invitation(monkeypatch) -> None:
    email = unique_email("verified-invite-accept")

    _, token = create_pending_invitation(monkeypatch, email=email)
    user = create_existing_user(email=email, verified=True)

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        response = client.post(
            TEAM_ACCEPT_URL,
            json={"token": token},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization_id"]
    assert body["membership_id"]

    with TestingSessionLocal() as db:
        invitation = db.scalar(
            select(TeamInvitation).where(
                TeamInvitation.token_hash == hash_invitation_token(token)
            )
        )
        assert invitation is not None
        assert invitation.status == "accepted"
        assert invitation.accepted_by_user_id == user.id


def count_memberships_for(user_email: str, organization_id: UUID) -> int:
    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == user_email))
        if user is None:
            return 0
        return len(
            db.scalars(
                select(Membership).where(
                    Membership.user_id == user.id,
                    Membership.organization_id == organization_id,
                )
            ).all()
        )


def test_revoked_invitation_cannot_be_accepted(monkeypatch) -> None:
    email = unique_email("revoked-team-accept")
    invitation_id, token = create_pending_invitation(monkeypatch, email=email)
    user = create_existing_user(email=email, verified=True)

    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        invitation.status = "revoked"
        organization_id = invitation.organization_id
        db.commit()

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        response = client.post(TEAM_ACCEPT_URL, json={"token": token})

    assert response.status_code == 409, response.text
    assert count_memberships_for(email, organization_id) == 0


def test_accepted_invitation_token_cannot_be_reused(monkeypatch) -> None:
    email = unique_email("reused-team-accept")
    invitation_id, token = create_pending_invitation(monkeypatch, email=email)
    user = create_existing_user(email=email, verified=True)

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        first = client.post(TEAM_ACCEPT_URL, json={"token": token})
        second = client.post(TEAM_ACCEPT_URL, json={"token": token})

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        assert invitation.status == "accepted"
    assert count_memberships_for(email, UUID(first.json()["organization_id"])) == 1


def test_expired_invitation_cannot_be_accepted(monkeypatch) -> None:
    email = unique_email("expired-team-accept")
    invitation_id, token = create_pending_invitation(monkeypatch, email=email)
    user = create_existing_user(email=email, verified=True)

    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        organization_id = invitation.organization_id
        db.commit()

    app = create_team_test_app(user=user)
    with TestClient(app) as client:
        response = client.post(TEAM_ACCEPT_URL, json={"token": token})

    assert response.status_code == 410, response.text
    with TestingSessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        assert invitation.status == "expired"
    assert count_memberships_for(email, organization_id) == 0
