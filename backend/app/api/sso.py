"""SIBVO SSO integration for Dealsflo."""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urljoin
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.service import create_authorization_audit_event
from app.auth.cookie import set_session_cookie
from app.auth.password import hash_password
from app.auth.service import create_session
from app.config import get_settings
from app.db.models.audit_event import AuditDecision
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.sibvo_identity_link import SibvoIdentityLink
from app.db.models.sibvo_organization_link import SibvoOrganizationLink
from app.db.models.team_invitation import TeamInvitation
from app.db.models.user import User
from app.db.session import get_db_session
from app.team.service import (
    InvitationExpiredError,
    accept_team_invitation,
    hash_invitation_token,
    provision_default_organization_roles,
)

router = APIRouter(prefix="/api/v1/sso", tags=["SSO"])


class SsoCallbackRequest(BaseModel):
    """Browser callback values. The verifier stays in an HttpOnly cookie."""

    code: str = Field(min_length=32, max_length=256)
    state: str = Field(min_length=16, max_length=256)


class SsoInvitationStartRequest(BaseModel):
    """One-time invitation token submitted in a request body, not a URL."""

    token: str = Field(min_length=32, max_length=512)


def _digest(value: str) -> str:
    """Hash an opaque value before comparison or storage."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pkce_s256(verifier: str) -> str:
    """Calculate an RFC 7636 S256 challenge."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _access_denied() -> HTTPException:
    """Return a generic authorization failure."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=("SIBVO access could not be linked to an eligible Dealsflo workspace."),
    )


def _flow_cookie(settings, state: str, verifier: str, nonce: str) -> str:
    """Serialize short-lived browser-flow data for an HttpOnly cookie."""
    return json.dumps(
        {"state": state, "verifier": verifier, "nonce": nonce},
        separators=(",", ":"),
    )


def _authorization_url(
    settings, organization_id: UUID, state: str, verifier: str, nonce: str
) -> str:
    base_url = settings.sso_sibvo_base_url.rstrip("/") + "/"
    if not base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise HTTPException(
            status_code=500,
            detail="Invalid SIBVO SSO provider configuration.",
        )

    query = urlencode(
        {
            "organization_id": str(organization_id),
            "response_type": "code",
            "client_id": settings.sso_dealsflo_client_id,
            "redirect_uri": settings.sso_dealsflo_redirect_uri,
            "scope": "openid email profile",
            "code_challenge": _pkce_s256(verifier),
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
        }
    )
    return urljoin(base_url, "sso/authorize") + "?" + query


def _new_flow(
    settings, organization_id: UUID, invitation_token: str | None = None
) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(32)
    cookie = json.loads(_flow_cookie(settings, state, verifier, nonce))
    if invitation_token is not None:
        cookie["invitation_token"] = invitation_token
    response_cookie = json.dumps(cookie, separators=(",", ":"))
    return _authorization_url(
        settings, organization_id, state, verifier, nonce
    ), response_cookie


def _set_flow_cookie(response, settings, raw_flow: str) -> None:
    response.set_cookie(
        key=settings.sso_flow_cookie_name,
        value=raw_flow,
        max_age=settings.sso_flow_cookie_max_age_seconds,
        httponly=True,
        secure=settings.sso_flow_cookie_secure,
        samesite="lax",
        path=settings.sso_flow_cookie_path,
    )


def _provision_sso_access(
    db: Session,
    *,
    subject: UUID,
    sibvo_organization_id: UUID,
    email: str,
    display_name: str,
    organization_name: str,
    organization_role: str,
    invitation_token: str | None,
) -> tuple[User, Organization]:
    """Provision explicit mappings through an entitled owner or one-time invite."""
    normalized_email = email.strip().casefold()
    normalized_role = organization_role.strip().casefold()
    if (
        len(normalized_email) > 320
        or "@" not in normalized_email
        or normalized_role not in {"owner", "admin", "member"}
    ):
        raise _access_denied()
    owner_access = normalized_role == "owner"

    organization_link = db.scalar(
        select(SibvoOrganizationLink)
        .where(SibvoOrganizationLink.sibvo_organization_id == sibvo_organization_id)
        .with_for_update()
    )
    created_organization = False
    if organization_link is None:
        if not owner_access:
            raise _access_denied()
        organization = Organization(
            name=" ".join(organization_name.split())[:200],
            is_active=True,
        )
        if not organization.name:
            raise _access_denied()
        db.add(organization)
        db.flush()
        organization_link = SibvoOrganizationLink(
            sibvo_organization_id=sibvo_organization_id,
            dealsflo_organization_id=organization.id,
        )
        db.add(organization_link)
        db.flush()
        created_organization = True
    else:
        organization = db.get(
            Organization,
            organization_link.dealsflo_organization_id,
        )
        if organization is None or not organization.is_active:
            raise _access_denied()

    identity_link = db.scalar(
        select(SibvoIdentityLink)
        .where(SibvoIdentityLink.sibvo_subject == subject)
        .with_for_update()
    )
    user = db.get(User, identity_link.dealsflo_user_id) if identity_link else None
    if identity_link is not None and user is None:
        raise _access_denied()

    invitation = None
    if invitation_token is not None:
        invitation = db.scalar(
            select(TeamInvitation)
            .where(TeamInvitation.token_hash == hash_invitation_token(invitation_token))
            .with_for_update()
        )
        if (
            invitation is None
            or invitation.organization_id != organization.id
            or invitation.email.strip().casefold() != normalized_email
            or invitation.status not in {"pending", "accepted"}
        ):
            raise _access_denied()

    if user is None:
        if invitation is None and not owner_access:
            raise _access_denied()

        existing_user = db.scalar(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        if existing_user is not None:
            # Existing accounts are only linked after a valid, email-bound invite.
            if invitation is None or not existing_user.is_email_verified:
                raise _access_denied()
            user = existing_user
        else:
            user = User(
                email=normalized_email,
                display_name=" ".join(display_name.split())[:200] or normalized_email,
                password_hash=hash_password(secrets.token_urlsafe(48)),
                is_active=True,
                is_email_verified=True,
            )
            db.add(user)
            db.flush()
        identity_link = SibvoIdentityLink(
            sibvo_subject=subject,
            dealsflo_user_id=user.id,
        )
        db.add(identity_link)
        db.flush()
        create_authorization_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            action="sso.identity_link.created",
            decision=AuditDecision.ALLOWED,
            resource_type="sibvo_identity",
            resource_id=str(subject),
        )

    if not user.is_active or not user.is_email_verified:
        raise _access_denied()

    membership = db.scalar(
        select(Membership)
        .where(
            Membership.user_id == user.id,
            Membership.organization_id == organization.id,
        )
        .with_for_update()
    )
    if invitation is not None:
        if invitation.status == "accepted":
            if (
                invitation.accepted_by_user_id != user.id
                or membership is None
                or not membership.is_active
            ):
                raise _access_denied()
        else:
            try:
                accept_team_invitation(
                    db,
                    raw_token=invitation_token,
                    user=user,
                )
            except InvitationExpiredError:
                raise _access_denied() from None
            create_authorization_audit_event(
                db,
                user_id=user.id,
                organization_id=organization.id,
                action="sso.invitation.accepted",
                decision=AuditDecision.ALLOWED,
                resource_type="team_invitation",
                resource_id=str(invitation.id),
            )
    elif membership is None:
        if not owner_access:
            raise _access_denied()
        owner_role = provision_default_organization_roles(
            db,
            organization_id=organization.id,
        )
        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            is_active=True,
        )
        db.add(membership)
        db.flush()
        db.add(MembershipRole(membership_id=membership.id, role_id=owner_role.id))
        create_authorization_audit_event(
            db,
            user_id=user.id,
            organization_id=organization.id,
            action=(
                "sso.organization.provisioned"
                if created_organization
                else "sso.organization_membership.provisioned"
            ),
            decision=AuditDecision.ALLOWED,
            resource_type="organization",
            resource_id=str(organization.id),
        )
    elif not membership.is_active:
        # Revoked local memberships require an administrator to re-invite.
        raise _access_denied()

    if not user.is_active or not organization.is_active:
        raise _access_denied()
    return user, organization


@router.get("/start")
def start_sso(organization_id: UUID) -> RedirectResponse:
    """Start SSO for the organization selected in the SIBVO application."""
    settings = get_settings()

    if not settings.sso_dealsflo_client_secret:
        raise HTTPException(
            status_code=503,
            detail="SSO is not configured.",
        )

    authorize_url, raw_flow = _new_flow(settings, organization_id)
    response = RedirectResponse(
        authorize_url,
        status_code=status.HTTP_302_FOUND,
    )
    _set_flow_cookie(response, settings, raw_flow)
    return response


@router.post("/start-invitation")
def start_invitation_sso(
    payload: SsoInvitationStartRequest,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    """Start SSO from a one-time invitation without putting its token in URLs."""
    settings = get_settings()
    if not settings.sso_dealsflo_client_secret:
        raise HTTPException(status_code=503, detail="SSO is not configured.")

    invitation = db.scalar(
        select(TeamInvitation).where(
            TeamInvitation.token_hash == hash_invitation_token(payload.token),
            TeamInvitation.status == "pending",
        )
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation is invalid or no longer available.",
        )
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired.",
        )

    organization_link = db.scalar(
        select(SibvoOrganizationLink).where(
            SibvoOrganizationLink.dealsflo_organization_id == invitation.organization_id
        )
    )
    if organization_link is None:
        raise _access_denied()

    authorization_url, raw_flow = _new_flow(
        settings,
        organization_link.sibvo_organization_id,
        payload.token,
    )
    response = JSONResponse({"authorization_url": authorization_url})
    _set_flow_cookie(response, settings, raw_flow)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/callback")
def finish_sso(
    payload: SsoCallbackRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> JSONResponse:
    """Exchange a code and create a local Dealsflo session."""
    settings = get_settings()

    raw_flow = request.cookies.get(settings.sso_flow_cookie_name)
    if not raw_flow:
        raise HTTPException(
            status_code=400,
            detail="The SSO flow expired. Start sign-in again.",
        )

    try:
        flow = json.loads(raw_flow)
        expected_state = flow["state"]
        verifier = flow["verifier"]
        nonce = flow["nonce"]
        invitation_token = flow.get("invitation_token")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=400,
            detail="The SSO flow is invalid. Start sign-in again.",
        ) from None

    if not all(isinstance(value, str) for value in (expected_state, verifier, nonce)):
        raise HTTPException(
            status_code=400,
            detail="The SSO flow is invalid. Start sign-in again.",
        )

    if not hmac.compare_digest(expected_state, payload.state):
        raise HTTPException(
            status_code=400,
            detail="SSO state validation failed.",
        )

    secret = settings.sso_dealsflo_client_secret
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="SSO is not configured.",
        )

    token_url = urljoin(
        settings.sso_sibvo_base_url.rstrip("/") + "/",
        "sso/token",
    )

    if invitation_token is not None and not isinstance(invitation_token, str):
        raise HTTPException(
            status_code=400,
            detail="The SSO flow is invalid. Start sign-in again.",
        )

    try:
        with httpx.Client(
            timeout=settings.sso_http_timeout_seconds,
            follow_redirects=False,
        ) as client:
            token_response = client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": payload.code,
                    "redirect_uri": settings.sso_dealsflo_redirect_uri,
                    "code_verifier": verifier,
                },
                auth=(
                    settings.sso_dealsflo_client_id,
                    secret.get_secret_value(),
                ),
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            token = token_data["id_token"]
            jwks_response = client.get(
                settings.sso_sibvo_base_url.rstrip("/") + "/sso/jwks"
            )
            jwks_response.raise_for_status()
            jwk_set = KeySet.import_key_set(jwks_response.json())
            verified = jwt.decode(
                token,
                jwk_set,
                algorithms=["RS256"],
            )
            claims = verified.claims
            JWTClaimsRegistry(
                iss={"essential": True, "value": settings.sso_sibvo_base_url},
                aud={"essential": True, "value": settings.sso_dealsflo_client_id},
                sub={"essential": True},
                exp={"essential": True},
                iat={"essential": True},
                nonce={"essential": True, "value": nonce},
            ).validate(claims)
    except (httpx.HTTPError, ValueError, KeyError, JoseError):
        raise HTTPException(
            status_code=502,
            detail="SIBVO sign-in could not be completed. Please retry.",
        ) from None

    try:
        subject = UUID(str(claims["sub"]))
        sibvo_session_id = UUID(str(claims["sid"]))
        sibvo_organization_id = UUID(str(claims["organization_id"]))
        organization_role = claims["organization_role"]
        organization_name = claims["organization_name"]
        if not isinstance(claims["email"], str) or claims["email_verified"] is not True:
            raise ValueError("Invalid email claim.")
        if (
            not isinstance(claims["name"], str)
            or not isinstance(organization_role, str)
            or not isinstance(organization_name, str)
        ):
            raise TypeError("Invalid identity or organization claim.")
    except (KeyError, TypeError, ValueError, JoseError):
        raise HTTPException(
            status_code=502,
            detail="SIBVO returned an invalid identity response.",
        ) from None

    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=settings.auth_session_lifetime_hours)

    try:
        user, organization = _provision_sso_access(
            db,
            subject=subject,
            sibvo_organization_id=sibvo_organization_id,
            email=claims["email"],
            display_name=claims["name"],
            organization_name=organization_name,
            organization_role=organization_role,
            invitation_token=invitation_token,
        )
        _session, raw_session_token = create_session(
            db=db,
            user=user,
            expires_at=expires_at,
            organization=organization,
            sibvo_subject=subject,
            sibvo_organization_id=sibvo_organization_id,
            sibvo_session_id=sibvo_session_id,
            sso_last_verified_at=now,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to create a Dealsflo session.",
        ) from None

    response = JSONResponse(
        {
            "user_id": str(user.id),
            "organization_id": str(organization.id),
        }
    )
    set_session_cookie(
        response=response,
        token=raw_session_token,
        expires_at=expires_at,
        settings=settings,
    )
    response.delete_cookie(
        key=settings.sso_flow_cookie_name,
        path=settings.sso_flow_cookie_path,
        httponly=True,
        secure=settings.sso_flow_cookie_secure,
        samesite="lax",
    )
    return response
