
"""Authentication API routes for DealFlow."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.cookie import (
    clear_session_cookie,
    get_session_cookie,
    set_session_cookie,
)
from app.auth.dependencies import get_current_user
from app.auth.login import authenticate_user
from app.auth.password import hash_password
from app.auth.schemas import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
)
from app.auth.service import create_session, revoke_session
from app.config import get_settings
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db_session

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


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
    """Create a user, workspace, owner membership, and authenticated session."""
    settings = get_settings()
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

        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=settings.auth_session_lifetime_hours
        )

        _, token = create_session(
            db=db,
            user=user,
            expires_at=expires_at,
        )
        db.commit()

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

    set_session_cookie(
        response=response,
        token=token,
        expires_at=expires_at,
        settings=settings,
    )

    return SignupResponse(
        user=user,
        organization={
            "id": organization.id,
            "name": organization.name,
        },
    )


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
    """Authenticate a user and create a server-side session."""
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
    token = get_session_cookie(
        request=request,
        settings=settings,
    )

    try:
        if token:
            revoke_session(
                db=db,
                token=token,
            )
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        clear_session_cookie(
            response=response,
            settings=settings,
        )


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
