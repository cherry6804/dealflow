
"""Authentication API routes for DealFlow."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.cookie import (
    clear_session_cookie,
    get_session_cookie,
    set_session_cookie,
)
from app.auth.dependencies import get_current_user
from app.auth.email_outbox import enqueue_verification_email
from app.auth.email_verification import (
    consume_verification_token,
    create_verification_token,
)
from app.auth.login import authenticate_user
from app.auth.password import hash_password
from app.auth.schemas import (
    LoginRequest,
    LoginResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.auth.service import create_session, revoke_session
from app.config import get_settings
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db_session

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

RESEND_GENERIC_MESSAGE = (
    "If the account exists and needs verification, "
    "a verification email will be sent when eligible."
)


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    payload: SignupRequest,
    response: Response,
    db: Session = Depends(get_db_session),
) -> SignupResponse:
    """Create a pending user, workspace, verification token, and email job."""
    del response  # Signup deliberately does not set an authentication cookie.

    normalized_email = payload.email.strip().lower()

    existing_user = db.scalar(
        select(User.id).where(User.email == normalized_email)
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    owner_role = db.scalar(
        select(Role).where(
            Role.name == "DealFlow Owner",
            Role.is_active.is_(True),
        )
    )
    if owner_role is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signup is temporarily unavailable. Please try again later.",
        )

    user = User(
        email=normalized_email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_email_verified=False,
    )
    organization = Organization(
        name=payload.organization_name,
        is_active=True,
    )

    try:
        db.add_all([user, organization])
        db.flush()

        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            is_active=True,
        )
        db.add(membership)
        db.flush()

        db.add(
            MembershipRole(
                membership_id=membership.id,
                role_id=owner_role.id,
            )
        )
        db.flush()

        _, raw_token = create_verification_token(db, user=user)

        # The encrypted email job is committed atomically with the user,
        # workspace, membership, role assignment, and verification token.
        # No email is delivered inside the signup request.
        enqueue_verification_email(
            db,
            recipient=user.email,
            token=raw_token,
        )

        db.commit()
        db.refresh(user)
        db.refresh(organization)

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email already exists or signup "
                "conflicts with existing data."
            ),
        ) from exc
    except Exception:
        db.rollback()
        raise

    return SignupResponse(
        user=user,
        organization={
            "id": organization.id,
            "name": organization.name,
        },
        verification_required=True,
    )


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    status_code=status.HTTP_200_OK,
)
def verify_email(
    payload: VerifyEmailRequest,
    db: Session = Depends(get_db_session),
) -> VerifyEmailResponse:
    """Verify an account using a valid, unexpired, single-use token."""
    try:
        user = consume_verification_token(db, token=payload.token)
        if user is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This verification link is invalid or has expired.",
            )

        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    return VerifyEmailResponse(
        message="Your email address has been verified. You can now sign in."
    )


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    status_code=status.HTTP_200_OK,
)
def resend_verification(
    payload: ResendVerificationRequest,
    db: Session = Depends(get_db_session),
) -> ResendVerificationResponse:
    """Queue a replacement verification email without disclosing account state."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    normalized_email = payload.email.strip().lower()
    cutoff = now - timedelta(hours=1)

    try:
        user = db.scalar(
            select(User)
            .where(User.email == normalized_email)
            .with_for_update()
        )

        if user is None or not user.is_active or user.is_email_verified:
            return ResendVerificationResponse(
                message=RESEND_GENERIC_MESSAGE
            )

        recent_count = (
            db.scalar(
                select(func.count())
                .select_from(EmailVerificationToken)
                .where(
                    EmailVerificationToken.user_id == user.id,
                    EmailVerificationToken.created_at >= cutoff,
                )
            )
            or 0
        )

        latest_token = db.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.created_at.desc())
            .limit(1)
        )

        if latest_token is not None:
            created_at = latest_token.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            cooldown_end = created_at + timedelta(
                seconds=settings.email_verification_resend_cooldown_seconds
            )
            if now < cooldown_end:
                return ResendVerificationResponse(
                    message=RESEND_GENERIC_MESSAGE
                )

        if recent_count >= settings.email_verification_max_resends_per_hour:
            return ResendVerificationResponse(
                message=RESEND_GENERIC_MESSAGE
            )

        # Invalidate outstanding tokens and queue the replacement job in
        # the same transaction. If enqueueing fails, rollback restores the
        # previous token state and removes the newly created token.
        outstanding_tokens = db.scalars(
            select(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.used_at.is_(None),
            )
            .with_for_update()
        ).all()

        for old_token in outstanding_tokens:
            old_token.used_at = now

        _, raw_token = create_verification_token(db, user=user, now=now)

        enqueue_verification_email(
            db,
            recipient=user.email,
            token=raw_token,
            now=now,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return ResendVerificationResponse(message=RESEND_GENERIC_MESSAGE)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db_session),
) -> LoginResponse:
    """Authenticate a verified user and create a server-side session."""
    settings = get_settings()

    user = authenticate_user(
        db=db,
        email=payload.email,
        password=payload.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address before signing in.",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.auth_session_lifetime_hours
    )

    try:
        _, token = create_session(
            db=db,
            user=user,
            expires_at=expires_at,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    set_session_cookie(
        response=response,
        token=token,
        expires_at=expires_at,
        settings=settings,
    )

    return LoginResponse(user=user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
) -> None:
    """Revoke the current session and clear the authentication cookie."""
    settings = get_settings()
    token = get_session_cookie(request=request, settings=settings)

    try:
        if token:
            revoke_session(db=db, token=token)
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        clear_session_cookie(response=response, settings=settings)


@router.get(
    "/me",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def get_me(
    user: User = Depends(get_current_user),
) -> LoginResponse:
    """Return the authenticated user's safe identity."""
    return LoginResponse(user=user)
