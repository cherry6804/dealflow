"""Bootstrap the first DealFlow owner account and organization.

This script is intended for local development and initial setup.
It does not overwrite existing users, roles, or permissions.
"""

from getpass import getpass

from app.auth.password import hash_password
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal
from sqlalchemy import select

OWNER_ROLE_NAME = "DealFlow Owner"

REQUIRED_PERMISSIONS = (
    "contacts.create",
    "contacts.read",
    "contacts.update",
    "leads.create",
    "leads.read",
    "leads.update",
    "properties.create",
    "properties.read",
    "properties.update",
    "requirements.create",
    "requirements.read",
    "requirements.update",
    "imports.upload",
)


def main() -> None:
    print("\nDealFlow initial owner setup")
    print("-" * 32)

    display_name = input("Your display name: ").strip()
    email = input("Login email: ").strip().lower()
    organization_name = input("Organization name: ").strip()

    if not display_name or len(display_name) > 200:
        raise SystemExit("Display name is required and must be <= 200 characters.")

    if not email or len(email) > 320 or "@" not in email:
        raise SystemExit("Enter a valid email address.")

    if not organization_name or len(organization_name) > 200:
        raise SystemExit("Organization name is required and must be <= 200 characters.")

    password = getpass("Password (input hidden): ")
    confirmation = getpass("Confirm password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    if len(password) < 12:
        raise SystemExit("Use a password with at least 12 characters.")

    password_hash = hash_password(password)

    # Avoid retaining plaintext credentials longer than necessary.
    del password
    del confirmation

    with SessionLocal() as session, session.begin():
        existing_user = session.scalar(
            select(User.id).where(User.email == email)
        )
        if existing_user is not None:
            raise SystemExit(
                "That email already exists. No changes were made."
            )

        existing_role = session.scalar(
            select(Role.id).where(Role.name == OWNER_ROLE_NAME)
        )
        if existing_role is not None:
            raise SystemExit(
                f"Role '{OWNER_ROLE_NAME}' already exists. "
                "Review the existing setup before proceeding."
            )

        permissions = list(
            session.scalars(
                select(Permission).where(
                    Permission.key.in_(REQUIRED_PERMISSIONS),
                    Permission.is_active.is_(True),
                )
            )
        )
        permissions_by_key = {
            permission.key: permission for permission in permissions
        }

        missing_permissions = sorted(
            set(REQUIRED_PERMISSIONS) - set(permissions_by_key)
        )
        if missing_permissions:
            raise SystemExit(
                "Required active permissions are missing: "
                + ", ".join(missing_permissions)
                + ". No changes were made."
            )

        user = User(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_active=True,
        )

        organization = Organization(
            name=organization_name,
            is_active=True,
        )

        role = Role(
            name=OWNER_ROLE_NAME,
            description=(
                "Initial DealFlow owner role for the current "
                "Contacts, Leads, Properties, and Requirements APIs."
            ),
            is_active=True,
        )

        session.add_all([user, organization, role])
        session.flush()

        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            is_active=True,
        )
        session.add(membership)
        session.flush()

        for permission_key in REQUIRED_PERMISSIONS:
            session.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permissions_by_key[permission_key].id,
                )
            )

        session.add(
            MembershipRole(
                membership_id=membership.id,
                role_id=role.id,
            )
        )

        session.flush()

        user_id = str(user.id)
        organization_id = str(organization.id)
        role_id = str(role.id)

        # The transaction has committed successfully here.

    print("\nOwner account created successfully.")
    print(f"Email: {email}")
    print(f"Organization: {organization_name}")
    print(f"Role: {OWNER_ROLE_NAME}")
    print(f"Permissions assigned: {len(REQUIRED_PERMISSIONS)}")
    print(f"User ID: {user_id}")
    print(f"Organization ID: {organization_id}")
    print(f"Role ID: {role_id}")
    print("\nYou can now try signing in through the DealFlow frontend.")


if __name__ == "__main__":
    main()