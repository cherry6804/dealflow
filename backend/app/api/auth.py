"""Authentication API routes for DealFlow."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.cookie import (
    clear_session_cookie,
    get_session_cookie,
    set_session_cookie,
)
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user,
    get_current_user_context,
)
from app.auth.email_outbox import (
    enqueue_password_reset_email,
    enqueue_verification_email,
)
from app.auth.email_verification import (
    consume_verification_token,
    create_verification_token,
)
from app.auth.login import authenticate_user
from app.auth.password import hash_password
from app.auth.password_reset import (
    consume_password_reset_token,
    create_password_reset_token,
    invalidate_password_reset_tokens,
)
from app.auth.rate_limit import consume_login_attempt
from app.auth.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.auth.service import create_session, revoke_session
from app.config import get_settings
from app.db.models.auth_session import AuthSession
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User
from app.db.session import get_db_session
from app.integrations import sibvo_client
from app.integrations.sibvo_client import SibvoError
from app.team.service import provision_default_organization_roles

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

RESEND_GENERIC_MESSAGE = (
    "If the account exists and needs verification, "
    "a verification email will be sent when eligible."
)

PASSWORD_RESET_GENERIC_MESSAGE = (
    "If an eligible account exists for this email, "
    "a password-reset email will be sent when eligible."
)

PASSWORD_RESET_INVALID_MESSAGE = "This password-reset link is invalid or has expired."


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
    """Create a user, organization, Owner membership and verification email."""
    del response

    if get_settings().app_environment == "production":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Create your account through SIBVO.",
        )

    normalized_email = payload.email.strip().lower()

    existing_user = db.scalar(
        select(User.id).where(func.lower(User.email) == normalized_email)
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
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

        # Provision the scoped roles inside the same transaction as signup.
        # This does not assign the legacy global Owner role.
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

        db.add(
            MembershipRole(
                membership_id=membership.id,
                role_id=owner_role.id,
            )
        )
        db.flush()

        _, raw_token = create_verification_token(db, user=user)
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
    now = datetime.now(UTC)
    normalized_email = payload.email.strip().lower()
    cutoff = now - timedelta(hours=1)

    try:
        user = db.scalar(
            select(User)
            .where(func.lower(User.email) == normalized_email)
            .with_for_update()
        )

        if user is None or not user.is_active or user.is_email_verified:
            return ResendVerificationResponse(message=RESEND_GENERIC_MESSAGE)

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
                created_at = created_at.replace(tzinfo=UTC)

            cooldown_end = created_at + timedelta(
                seconds=settings.email_verification_resend_cooldown_seconds
            )
            if now < cooldown_end:
                return ResendVerificationResponse(message=RESEND_GENERIC_MESSAGE)

        if recent_count >= settings.email_verification_max_resends_per_hour:
            return ResendVerificationResponse(message=RESEND_GENERIC_MESSAGE)

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

        _, raw_token = create_verification_token(
            db,
            user=user,
            now=now,
        )
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
    "/password-reset/request",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db_session),
) -> PasswordResetResponse:
    """Queue a password-reset email without disclosing account existence."""
    settings = get_settings()
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=1)
    normalized_email = str(payload.email).strip().lower()

    try:
        user = db.scalar(
            select(User)
            .where(func.lower(User.email) == normalized_email)
            .with_for_update()
        )

        if user is None or not user.is_active:
            return PasswordResetResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)

        recent_count = (
            db.scalar(
                select(func.count())
                .select_from(PasswordResetToken)
                .where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.created_at >= cutoff,
                )
            )
            or 0
        )

        latest_token = db.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id)
            .order_by(PasswordResetToken.created_at.desc())
            .limit(1)
        )

        if latest_token is not None:
            created_at = latest_token.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)

            cooldown_end = created_at + timedelta(
                seconds=settings.password_reset_request_cooldown_seconds
            )
            if now < cooldown_end:
                return PasswordResetResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)

        if recent_count >= settings.password_reset_max_requests_per_hour:
            return PasswordResetResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)

        invalidate_password_reset_tokens(db, user.id, now=now)

        _, raw_token = create_password_reset_token(
            db,
            user.id,
            now=now,
        )
        enqueue_password_reset_email(
            db,
            recipient=user.email,
            token=raw_token,
            now=now,
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    return PasswordResetResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)


@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Session = Depends(get_db_session),
) -> PasswordResetResponse:
    """Reset a password and revoke all existing sessions atomically."""
    now = datetime.now(UTC)

    try:
        reset_record = consume_password_reset_token(
            db,
            token=payload.token,
            now=now,
        )

        if reset_record is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PASSWORD_RESET_INVALID_MESSAGE,
            )

        user = db.scalar(
            select(User).where(User.id == reset_record.user_id).with_for_update()
        )

        if user is None or not user.is_active:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PASSWORD_RESET_INVALID_MESSAGE,
            )

        user.password_hash = hash_password(payload.new_password)

        invalidate_password_reset_tokens(db, user.id, now=now)

        db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

        db.commit()

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    return PasswordResetResponse(
        message="Your password has been reset. You can now sign in."
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
) -> LoginResponse:
    """Authenticate a verified user and create a server-side session."""
    settings = get_settings()

    if settings.app_environment == "production":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Sign in through SIBVO.",
        )

    client_key = request.client.host if request.client is not None else "unknown"
    allowed, retry_after = consume_login_attempt(
        db,
        client_key=f"login:{client_key}",
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

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

    expires_at = datetime.now(UTC) + timedelta(
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


@router.get(
    "/sibvo-access",
    status_code=status.HTTP_200_OK,
)
def get_sibvo_access(
    context: CurrentUserContext = Depends(get_current_user_context),
) -> dict:
    """Return SIBVO's access snapshot for this session (read-only).

    SIBVO owns subscription, billing, and entitlement state; Dealsflo only
    displays what SIBVO last returned for the signed-in session.
    """
    if not context.sibvo_attested or context.sibvo_access is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SIBVO access information for this session.",
        )
    return context.sibvo_access


@router.get(
    "/sibvo-seats",
    status_code=status.HTTP_200_OK,
)
def get_sibvo_seats(
    context: CurrentUserContext = Depends(get_current_user_context),
) -> dict:
    """Return SIBVO's seat capacity for this session's organization.

    SIBVO is the only seat authority. Capacity is read from SIBVO on each call
    and is shown to product owners only. Failures are reported as unavailable.
    """
    if (
        not context.sibvo_attested
        or context.sibvo_access is None
        or context.sibvo_subject is None
        or context.sibvo_session_id is None
        or context.sibvo_organization_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SIBVO access information for this session.",
        )
    if context.sibvo_access.get("product_role") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seat capacity is shown to product owners.",
        )
    try:
        usage = sibvo_client.fetch_seat_usage(
            get_settings(),
            subject=context.sibvo_subject,
            session_id=context.sibvo_session_id,
            organization_id=context.sibvo_organization_id,
        )
    except SibvoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SIBVO seat information is unavailable.",
        ) from None
    if usage is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seat capacity is not available for this session.",
        )
    return {
        "seat_limit": usage.seat_limit,
        "allocated": usage.allocated,
        "reserved": usage.reserved,
        "available": usage.available,
        "unlimited": usage.seat_limit is None,
    }
