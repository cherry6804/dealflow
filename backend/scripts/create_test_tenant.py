
"""Create a separate local tenant and test login for manual testing."""

from getpass import getpass

from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import SessionLocal

OWNER_ROLE_NAME = "DealFlow Owner"


def main() -> None:
    print("\nDealFlow - Create Manual Test Tenant")
    print("-" * 38)

    organization_name = input("Organization name: ").strip()
    display_name = input("Test user's display name: ").strip()
    email = input("New login email: ").strip().lower()

    if not organization_name or len(organization_name) > 200:
        raise SystemExit("Organization name is required (max 200 characters).")
    if not display_name or len(display_name) > 200:
        raise SystemExit("Display name is required (max 200 characters).")
    if not email or len(email) > 320 or "@" not in email:
        raise SystemExit("Enter a valid email address.")

    password = getpass("Password (minimum 12 characters): ")
    confirmation = getpass("Confirm password: ")

    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    password_hash = hash_password(password)
    del password, confirmation

    with SessionLocal() as session, session.begin():
        existing_user = session.scalar(
            select(User.id).where(User.email == email)
        )
        if existing_user is not None:
            raise SystemExit("That email already exists. No changes made.")

        role = session.scalar(
            select(Role).where(
                Role.name == OWNER_ROLE_NAME,
                Role.is_active.is_(True),
            )
        )
        if role is None:
            raise SystemExit(
                f"Active role '{OWNER_ROLE_NAME}' not found. No changes made."
            )

        organization = Organization(
            name=organization_name,
            is_active=True,
        )
        user = User(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_active=True,
        )

        session.add_all([organization, user])
        session.flush()

        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            is_active=True,
        )
        session.add(membership)
        session.flush()

        session.add(
            MembershipRole(
                membership_id=membership.id,
                role_id=role.id,
            )
        )

        organization_id = str(organization.id)
        user_id = str(user.id)

    print("\nTest tenant created successfully.")
    print(f"Organization: {organization_name}")
    print(f"Organization ID: {organization_id}")
    print(f"User ID: {user_id}")
    print(f"Login email: {email}")
    print(f"Assigned role: {OWNER_ROLE_NAME}")


if __name__ == "__main__":
    main()
