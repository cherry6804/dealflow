"""Seed a TEST-ONLY Dealsflo identity link and membership for the E12 demo non-owner.

This records the state an accepted Dealsflo invitation produces: a local user, an explicit
SIBVO identity link, and an active organization membership with the Member role. It does
not bypass invitation validation for real users, and it sends no email.

The script refuses any database other than "dealflow_test". It refuses to link a SIBVO
subject that is already linked. It prints identifiers only.

Usage (from backend/, with DATABASE_URL set in the process environment):
    uv run python scripts/seed_e12_demo_member_link.py <sibvo-member-subject> <sibvo-org-id>
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.role import Role
from app.db.models.sibvo_identity_link import SibvoIdentityLink
from app.db.models.sibvo_organization_link import SibvoOrganizationLink
from app.db.models.user import User
from app.auth.password import hash_password

DEMO_EMAIL = "demo.member@e12demo.dev"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: seed_e12_demo_member_link.py <sibvo-member-subject> <sibvo-org-id>", file=sys.stderr)
        return 2
    subject = uuid.UUID(sys.argv[1])
    sibvo_org = uuid.UUID(sys.argv[2])

    url = get_settings().database_url
    if make_url(url).database != "dealflow_test":
        print("Refusing to seed: this script only runs against dealflow_test.", file=sys.stderr)
        return 2

    engine = create_engine(url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        org_link = db.scalar(
            select(SibvoOrganizationLink).where(SibvoOrganizationLink.sibvo_organization_id == sibvo_org)
        )
        if org_link is None:
            print("The SIBVO organization is not linked to a Dealsflo organization.", file=sys.stderr)
            return 3
        if db.scalar(select(SibvoIdentityLink).where(SibvoIdentityLink.sibvo_subject == subject)) is not None:
            print("This SIBVO subject is already linked. Nothing was changed.", file=sys.stderr)
            return 3

        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                display_name="Demo Member (TEST, seeded identity link)",
                password_hash=hash_password(uuid.uuid4().hex),  # never used: sign-in is through SIBVO
                is_active=True,
                is_email_verified=True,
            )
            db.add(user)
            db.flush()

        db.add(SibvoIdentityLink(sibvo_subject=subject, dealsflo_user_id=user.id))
        membership = Membership(
            user_id=user.id,
            organization_id=org_link.dealsflo_organization_id,
            is_active=True,
        )
        db.add(membership)
        db.flush()

        member_role = db.scalar(
            select(Role).where(Role.name == "Member", Role.organization_id == org_link.dealsflo_organization_id)
        )
        if member_role is None:
            print("The organization has no Member role. Nothing was changed.", file=sys.stderr)
            db.rollback()
            return 3
        db.add(MembershipRole(membership_id=membership.id, role_id=member_role.id))
        db.commit()

        print(
            {
                "dealsflo_user_id": str(user.id),
                "dealsflo_organization_id": str(org_link.dealsflo_organization_id),
                "membership_id": str(membership.id),
                "role": "Member",
                "label": "TEST-ONLY seeded identity link",
                "seeded_at": datetime.now(UTC).isoformat(),
            }
        )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
