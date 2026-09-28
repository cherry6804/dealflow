"""Authentication login services for DealFlow."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import verify_password
from app.db.models.user import User


def authenticate_user(
    db: Session,
    email: str,
    password: str,
) -> User | None:
    """Authenticate a user by email and password.

    Returns the active user when authentication succeeds.
    Returns None for invalid credentials or inactive users.
    """

    normalized_email = email.strip().lower()

    statement = select(User).where(
        User.email == normalized_email,
    )

    user = db.scalar(statement)

    if user is None:
        return None

    if not user.is_active:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user