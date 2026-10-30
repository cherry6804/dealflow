"""Remove a Dealsflo team member, release the SIBVO product seat, and record it.

Order of operations, chosen so a failure never reports success:

1. Validate the removal against the local membership (same rules as everywhere).
2. If the member is linked to SIBVO, ask SIBVO to revoke their Dealsflo product
   membership and release the seat. SIBVO's answer is required. If SIBVO does
   not confirm, nothing local changes and the request fails.
3. Deactivate the local membership, revoke the member's sessions in this
   organization, write the removal record and the audit event, then commit.

Retries are safe. The SIBVO call is idempotent, and an inactive membership whose
seat SIBVO confirms is reported as already removed. Only the product membership
changes in SIBVO. The organization membership and the global identity are never
modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit.service import create_authorization_audit_event
from app.config import Settings
from app.db.models.audit_event import AuditDecision
from app.db.models.auth_session import AuthSession
from app.db.models.sibvo_identity_link import SibvoIdentityLink
from app.db.models.sibvo_organization_link import SibvoOrganizationLink
from app.db.models.team_member_removal import TeamMemberRemoval
from app.integrations import sibvo_client
from app.integrations.sibvo_client import SibvoRequestDenied
from app.team.service import _get_organization_membership, assert_member_removable

SEAT_RELEASED = "released"
SEAT_ALREADY_RELEASED = "already_released"
SEAT_NOT_HELD = "not_held"
SEAT_NOT_LINKED = "not_linked"

NOT_CONFIRMED_DETAIL = "SIBVO did not confirm the removal. The member has not been removed. Try again."
IDEMPOTENCY_PREFIX = "team-removal-"


@dataclass(frozen=True)
class SibvoActor:
    """The signed-in administrator's SIBVO identifiers, taken from the server-side session."""

    subject: UUID | None
    session_id: UUID | None
    organization_id: UUID | None


@dataclass(frozen=True)
class MemberRemovalOutcome:
    membership_id: UUID
    is_active: bool
    seat_outcome: str
    already_removed: bool


def _sibvo_link(db: Session, *, user_id: UUID, organization_id: UUID) -> tuple[SibvoIdentityLink, SibvoOrganizationLink] | None:
    """Return the identity and organization links for a member, or None when neither exists."""
    identity = db.scalar(select(SibvoIdentityLink).where(SibvoIdentityLink.dealsflo_user_id == user_id))
    organization = db.scalar(
        select(SibvoOrganizationLink).where(SibvoOrganizationLink.dealsflo_organization_id == organization_id)
    )
    if identity is None and organization is None:
        return None
    if identity is None or organization is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This organization's SIBVO link is incomplete. Ask an administrator to check it.",
        )
    return identity, organization


def _release_seat_in_sibvo(
    settings: Settings,
    *,
    actor: SibvoActor,
    organization: SibvoOrganizationLink,
    identity: SibvoIdentityLink,
    membership_id: UUID,
    reason: str,
) -> str:
    if actor.subject is None or actor.session_id is None or actor.organization_id != organization.sibvo_organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign in through SIBVO to remove this member.",
        )
    try:
        result = sibvo_client.release_product_seat(
            settings,
            actor_subject=actor.subject,
            actor_session_id=actor.session_id,
            organization_id=organization.sibvo_organization_id,
            target_subject=identity.sibvo_subject,
            reason=reason,
            idempotency_key=f"{IDEMPOTENCY_PREFIX}{membership_id}",
        )
    except SibvoRequestDenied as denied:
        if denied.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SIBVO did not authorize this removal.",
            ) from None
        if denied.status_code == 409:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This member holds an owner seat in SIBVO and cannot be removed here.",
            ) from None
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_CONFIRMED_DETAIL) from None
    except sibvo_client.SibvoError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_CONFIRMED_DETAIL) from None

    if not result.released:
        return SEAT_NOT_HELD
    return SEAT_ALREADY_RELEASED if result.already_released else SEAT_RELEASED


def remove_member_and_release_seat(
    db: Session,
    *,
    settings: Settings,
    organization_id: UUID,
    membership_id: UUID,
    actor_user_id: UUID,
    actor: SibvoActor,
    reason: str,
) -> MemberRemovalOutcome:
    """Remove a team member. Raises HTTPException rather than reporting an unconfirmed removal."""
    membership = _get_organization_membership(
        db,
        organization_id=organization_id,
        membership_id=membership_id,
        lock=True,
    )
    assert_member_removable(
        db,
        organization_id=organization_id,
        membership=membership,
        actor_user_id=actor_user_id,
        allow_inactive=True,
    )

    links = _sibvo_link(db, user_id=membership.user_id, organization_id=organization_id)
    if links is None:
        seat_outcome = SEAT_NOT_LINKED
    else:
        identity, organization = links
        seat_outcome = _release_seat_in_sibvo(
            settings,
            actor=actor,
            organization=organization,
            identity=identity,
            membership_id=membership.id,
            reason=reason,
        )

    already_removed = not membership.is_active
    if already_removed:
        return MemberRemovalOutcome(
            membership_id=membership.id,
            is_active=False,
            seat_outcome=seat_outcome,
            already_removed=True,
        )

    now = datetime.now(UTC)
    membership.is_active = False
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == membership.user_id,
            AuthSession.organization_id == organization_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.add(
        TeamMemberRemoval(
            organization_id=organization_id,
            membership_id=membership.id,
            target_user_id=membership.user_id,
            actor_user_id=actor_user_id,
            reason=reason,
            seat_outcome=seat_outcome,
        )
    )
    create_authorization_audit_event(
        db,
        user_id=actor_user_id,
        organization_id=organization_id,
        action="team.member.removed",
        decision=AuditDecision.ALLOWED,
        permission_key="organization.members.manage",
        resource_type="organization_membership",
        resource_id=str(membership.id),
    )
    db.flush()
    return MemberRemovalOutcome(
        membership_id=membership.id,
        is_active=False,
        seat_outcome=seat_outcome,
        already_removed=False,
    )
