"""Removing a Dealsflo team member revokes their SIBVO product seat first.

SIBVO's answer is required before a removal is reported. The boundary is strict:
only the Dealsflo product membership is revoked in SIBVO. The global identity and
the organization membership are never changed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.team import router as team_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditEvent
from app.db.models.auth_session import AuthSession
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.role import Role
from app.db.models.sibvo_identity_link import SibvoIdentityLink
from app.db.models.sibvo_organization_link import SibvoOrganizationLink
from app.db.models.team_member_removal import TeamMemberRemoval
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session
from app.integrations import sibvo_client
from app.integrations.sibvo_client import (
    SibvoRequestDenied,
    SibvoSeatRelease,
    SibvoUnavailable,
)
from app.team.service import OWNER_ROLE_NAME
from tests.test_deals_api import create_authorized_user, create_membership, create_user
from tests.test_team_api import BASE_URL


def build_app(actor: CurrentUserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(team_router)

    def override_db() -> Iterator[Session]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user_context] = lambda: actor
    return app


def seed_linked_member(*, with_org_link: bool = True, identity: bool = True):
    """An organization with a SIBVO-attested administrator and one linked member."""
    db = SessionLocal()
    try:
        admin, organization = create_authorized_user(
            db, permission_keys=("organization.members.manage", "organization.members.read")
        )
        db.refresh(admin)
        db.refresh(organization)
        member = create_user(db)
        membership = create_membership(db, user=member, organization=organization)
        session_token = AuthSession(
            user_id=member.id,
            organization_id=organization.id,
            token_hash=uuid4().hex + uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(session_token)
        subject = uuid4()
        sibvo_org = uuid4()
        if identity:
            db.add(SibvoIdentityLink(sibvo_subject=subject, dealsflo_user_id=member.id))
        if with_org_link:
            db.add(
                SibvoOrganizationLink(
                    sibvo_organization_id=sibvo_org,
                    dealsflo_organization_id=organization.id,
                )
            )
        db.commit()
        data = {
            "admin_id": admin.id,
            "organization_id": organization.id,
            "member_id": member.id,
            "membership_id": membership.id,
            "subject": subject,
            "sibvo_org": sibvo_org,
        }
        return data
    finally:
        db.close()


def attested_admin(admin_id, sibvo_org) -> CurrentUserContext:
    return CurrentUserContext(
        user=SimpleNamespace(id=admin_id),  # type: ignore[arg-type]
        session_organization_id=None,
        sibvo_attested=True,
        sibvo_access={"product_role": "owner", "entitlements": []},
        sibvo_subject=uuid4(),
        sibvo_session_id=uuid4(),
        sibvo_organization_id=sibvo_org,
    )


def stub_release(monkeypatch: pytest.MonkeyPatch, *, result=None, error=None) -> list[dict]:
    calls: list[dict] = []

    def fake(settings, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(sibvo_client, "release_product_seat", fake)
    return calls


def member_state(membership_id) -> tuple[bool, int]:
    db = SessionLocal()
    try:
        membership = db.get(Membership, membership_id)
        removals = db.scalars(
            select(TeamMemberRemoval).where(TeamMemberRemoval.membership_id == membership_id)
        ).all()
        return membership.is_active, len(removals)
    finally:
        db.close()


def test_confirmed_removal_revokes_sessions_records_and_audits(monkeypatch):
    data = seed_linked_member()
    calls = stub_release(
        monkeypatch,
        result=SibvoSeatRelease(released=True, already_released=False, reason="released"),
    )
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        json={"reason": "Left the brokerage"},
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_active"] is False
    assert body["seat_outcome"] == "released"
    assert body["already_removed"] is False
    assert calls and calls[0]["target_subject"] == data["subject"]
    assert calls[0]["organization_id"] == data["sibvo_org"]
    db = SessionLocal()
    try:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == data["member_id"]))
        removal = db.scalar(select(TeamMemberRemoval).where(TeamMemberRemoval.membership_id == data["membership_id"]))
        audit = db.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(data["membership_id"])))
        identity = db.scalar(select(SibvoIdentityLink).where(SibvoIdentityLink.dealsflo_user_id == data["member_id"]))
        user = db.get(User, data["member_id"])
        assert session.revoked_at is not None
        assert removal.reason == "Left the brokerage"
        assert removal.seat_outcome == "released"
        assert removal.actor_user_id == data["admin_id"]
        assert audit is not None and audit.action == "team.member.removed"
        # Boundary: the global identity and the local user row are untouched.
        assert identity is not None
        assert user is not None and user.is_active is True
    finally:
        db.close()


def test_sibvo_outage_fails_closed_and_changes_nothing(monkeypatch):
    data = seed_linked_member()
    stub_release(monkeypatch, error=SibvoUnavailable("down"))
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    assert response.status_code == 503
    assert "SIBVO did not confirm the removal" in response.text
    assert member_state(data["membership_id"]) == (True, 0)


def test_sibvo_denial_is_reported_and_changes_nothing(monkeypatch):
    data = seed_linked_member()
    stub_release(monkeypatch, error=SibvoRequestDenied(403, "actor_not_authorized"))
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    assert response.status_code == 403
    assert member_state(data["membership_id"]) == (True, 0)


def test_owner_seat_in_sibvo_is_reported_as_a_conflict(monkeypatch):
    data = seed_linked_member()
    stub_release(monkeypatch, error=SibvoRequestDenied(409, "last_owner_or_owner_seat"))
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    assert response.status_code == 409
    assert member_state(data["membership_id"]) == (True, 0)


def test_retry_after_an_unconfirmed_attempt_completes_once(monkeypatch):
    data = seed_linked_member()
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))
    headers = {"X-Organization-ID": str(data["organization_id"])}

    stub_release(monkeypatch, error=SibvoUnavailable("down"))
    assert client.post(f"{BASE_URL}/members/{data['membership_id']}/remove", headers=headers).status_code == 503

    stub_release(
        monkeypatch,
        result=SibvoSeatRelease(released=True, already_released=False, reason="released"),
    )
    first = client.post(f"{BASE_URL}/members/{data['membership_id']}/remove", headers=headers)
    stub_release(
        monkeypatch,
        result=SibvoSeatRelease(released=True, already_released=True, reason="suspended"),
    )
    second = client.post(f"{BASE_URL}/members/{data['membership_id']}/remove", headers=headers)

    assert first.status_code == 200
    assert first.json()["already_removed"] is False
    assert second.status_code == 200
    assert second.json()["already_removed"] is True
    assert second.json()["seat_outcome"] == "already_released"
    assert member_state(data["membership_id"]) == (False, 1)


def test_member_without_sibvo_link_is_removed_locally_and_says_so(monkeypatch):
    data = seed_linked_member(with_org_link=False, identity=False)
    calls = stub_release(monkeypatch, error=AssertionError("must not call SIBVO"))
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    assert response.status_code == 200, response.text
    assert response.json()["seat_outcome"] == "not_linked"
    assert calls == []
    assert member_state(data["membership_id"]) == (False, 1)


def test_linked_removal_requires_sibvo_sign_in(monkeypatch):
    data = seed_linked_member()
    calls = stub_release(monkeypatch, error=AssertionError("must not call SIBVO"))
    unattested = CurrentUserContext(user=SimpleNamespace(id=data["admin_id"]))  # type: ignore[arg-type]
    client = TestClient(build_app(unattested))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    assert response.status_code == 403, response.text
    assert calls == []
    assert member_state(data["membership_id"]) == (True, 0)


def test_owner_membership_is_refused_before_sibvo_is_called(monkeypatch):
    data = seed_linked_member()
    db = SessionLocal()
    try:
        owner_role = db.scalar(select(Role).where(Role.name == OWNER_ROLE_NAME))
        if owner_role is None:
            owner_role = Role(name=OWNER_ROLE_NAME, organization_id=None, is_active=True)
            db.add(owner_role)
            db.flush()
        db.add(MembershipRole(membership_id=data["membership_id"], role_id=owner_role.id))
        db.commit()
    finally:
        db.close()
    calls = stub_release(monkeypatch, error=AssertionError("must not call SIBVO"))
    client = TestClient(build_app(attested_admin(data["admin_id"], data["sibvo_org"])))

    response = client.post(
        f"{BASE_URL}/members/{data['membership_id']}/remove",
        headers={"X-Organization-ID": str(data["organization_id"])},
    )

    # The only owner cannot be removed. The rule is checked before SIBVO is called.
    assert response.status_code == 409, response.text
    assert calls == []
    assert member_state(data["membership_id"]) == (True, 0)
