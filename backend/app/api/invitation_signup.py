"""Invitation-aware account registration for DealFlow."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.email_outbox import enqueue_verification_email
from app.auth.email_verification import create_verification_token
from app.auth.password import hash_password
from app.config import get_settings
from app.db.models.team_invitation import TeamInvitation
from app.db.models.user import User
from app.db.session import get_db_session
from app.team.service import hash_invitation_token

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class InvitationSignupRequest(BaseModel):
    """Register a user against a valid invitation."""

    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    invitation_token: str = Field(min_length=32, max_length=512)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if (
            not normalized
            or "@" not in normalized
            or "." not in normalized.rsplit("@", 1)[-1]
        ):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Enter your name.")
        return normalized


class InvitationSignupResponse(BaseModel):
    user: dict[str, str]
    verification_required: bool = True
    message: str


@router.post(
    "/signup-invitation",
    response_model=InvitationSignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup_from_invitation(
    payload: InvitationSignupRequest,
    db: Session = Depends(get_db_session),
) -> InvitationSignupResponse:
    """Create an unverified account for an existing workspace invitation."""
    if get_settings().app_environment == "production":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Accept workspace invitations through SIBVO.",
        )

    from datetime import datetime

    now = datetime.now(UTC)

    invitation = db.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.token_hash
            == hash_invitation_token(payload.invitation_token),
        )
        .with_for_update()
    )

    if invitation is None or invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is invalid, expired, or no longer available.",
        )

    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at <= now:
        invitation.status = "expired"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired. Ask the workspace administrator for a new invitation.",
        )

    normalized_email = payload.email.strip().lower()

    if normalized_email != invitation.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use the email address that received the invitation.",
        )

    existing_user = db.scalar(
        select(User).where(
            func.lower(User.email) == normalized_email,
        )
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email already exists. "
                "Sign in with that account to accept the invitation."
            ),
        )

    user = User(
        email=normalized_email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_email_verified=False,
    )

    try:
        db.add(user)
        db.flush()

        _, raw_verification_token = create_verification_token(
            db,
            user=user,
            now=now,
        )

        enqueue_verification_email(
            db,
            recipient=user.email,
            token=raw_verification_token,
            now=now,
        )

        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return InvitationSignupResponse(
        user={
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        },
        verification_required=True,
        message=(
            "Account created. Verify your email, sign in, and accept "
            "the invitation to join the workspace."
        ),
    )
