"""Authentication API routes for DealFlow."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.cookie import (
    clear_session_cookie,
    get_session_cookie,
    set_session_cookie,
)
from app.auth.dependencies import get_current_user
from app.auth.login import authenticate_user
from app.auth.schemas import LoginRequest, LoginResponse
from app.auth.service import create_session, revoke_session
from app.config import get_settings
from app.db.models.user import User
from app.db.session import get_db_session

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


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

    _, token = create_session(
        db=db,
        user=user,
        expires_at=expires_at,
    )

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

    if token:
        revoke_session(
            db=db,
            token=token,
        )

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