"""Authentication dependencies for DealFlow."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.cookie import get_session_cookie
from app.auth.service import get_active_session
from app.config import get_settings
from app.db.models.user import User
from app.db.session import get_db_session


def get_current_user(
    request: Request,
    db: Session = Depends(get_db_session),
) -> User:
    """Return the authenticated user associated with the current request."""
    settings = get_settings()

    token = get_session_cookie(
        request=request,
        settings=settings,
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    session = get_active_session(
        db=db,
        token=token,
    )

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = session.user

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return user