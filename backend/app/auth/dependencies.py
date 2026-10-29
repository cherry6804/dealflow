
"""Authentication and current-user dependencies for DealFlow."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.cookie import get_session_cookie
from app.auth.service import get_active_session
from app.config import get_settings
from app.db.models.user import User
from app.db.session import get_db_session


@dataclass(frozen=True)
class CurrentUserContext:
    """Represent the authenticated user for the current request."""

    user: User
    session_organization_id: UUID | None = None

    @property
    def user_id(self) -> UUID:
        """Return the authenticated user's identifier."""
        return self.user.id


def get_current_user_context(
    request: Request,
    db: Session = Depends(get_db_session),
) -> CurrentUserContext:
    """Return the authenticated user context for the current request."""
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

    if (
        settings.app_environment == "production"
        and session.organization_id is None
    ):
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

    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required.",
        )

    sibvo_values = (
        getattr(session, "sibvo_subject", None),
        getattr(session, "sibvo_organization_id", None),
        getattr(session, "sibvo_session_id", None),
    )
    has_sibvo_attestation = any(value is not None for value in sibvo_values)
    if has_sibvo_attestation:
        if any(value is None for value in sibvo_values):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )

        now = datetime.now(timezone.utc)
        last_verified = getattr(session, "sso_last_verified_at", None)
        if last_verified is not None and last_verified.tzinfo is None:
            last_verified = last_verified.replace(tzinfo=timezone.utc)

        should_revalidate = (
            last_verified is None
            or (now - last_verified).total_seconds()
            >= settings.sso_revalidation_interval_seconds
        )

        if should_revalidate:
            secret = settings.sso_dealsflo_client_secret
            if not secret:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="SIBVO access verification is unavailable.",
                )

            introspection_url = (
                settings.sso_sibvo_base_url.rstrip("/")
                + "/sso/introspect"
            )
            try:
                with httpx.Client(
                    timeout=settings.sso_http_timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = client.post(
                        introspection_url,
                        data={
                            "subject": str(sibvo_values[0]),
                            "session_id": str(sibvo_values[2]),
                            "organization_id": str(
                                sibvo_values[1]
                            ),
                        },
                        auth=(
                            settings.sso_dealsflo_client_id,
                            secret.get_secret_value(),
                        ),
                    )
                    response.raise_for_status()
                    access_active = response.json().get("active") is True
            except (httpx.HTTPError, ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="SIBVO access verification is unavailable.",
                ) from None

            if not access_active:
                session.revoked_at = now
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required.",
                )

            session.sso_last_verified_at = now
            db.commit()
    elif settings.app_environment == "production":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return CurrentUserContext(
        user=user,
        session_organization_id=session.organization_id,
    )


def get_current_user(
    context: CurrentUserContext = Depends(get_current_user_context),
) -> User:
    """Return the authenticated user for the current request."""
    return context.user
