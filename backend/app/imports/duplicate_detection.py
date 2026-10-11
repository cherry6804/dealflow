"""Shared tenant-scoped duplicate detection for contacts."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.contact import Contact


def normalize_email(value: object) -> str | None:
    """Normalize an email for duplicate comparisons."""
    if value is None:
        return None

    normalized = str(value).strip().casefold()
    return normalized or None


def normalize_phone(value: object) -> str | None:
    """Normalize a phone number by retaining digits only."""
    if value is None:
        return None

    normalized = re.sub(r"\D", "", str(value))
    return normalized or None


def load_existing_contact_keys(
    db: Session,
    organization_id: UUID,
) -> tuple[set[str], set[str]]:
    """Load email and phone keys belonging to one organization."""
    statement = select(Contact.email, Contact.phone).where(
        Contact.organization_id == organization_id
    )
    contacts = db.execute(statement).all()

    emails: set[str] = set()
    phones: set[str] = set()

    for email, phone in contacts:
        email_key = normalize_email(email)
        phone_key = normalize_phone(phone)

        if email_key:
            emails.add(email_key)

        if phone_key:
            phones.add(phone_key)

    return emails, phones


def duplicate_errors(
    row: dict[str, Any],
    *,
    existing_emails: set[str],
    existing_phones: set[str],
    seen_emails: set[str],
    seen_phones: set[str],
) -> list[dict[str, str]]:
    """Return duplicate-identifier errors without changing the supplied sets."""
    errors: list[dict[str, str]] = []

    email_key = normalize_email(row.get("email"))
    phone_key = normalize_phone(row.get("phone"))

    if email_key and (
        email_key in existing_emails or email_key in seen_emails
    ):
        errors.append(
            {
                "field": "email",
                "code": "duplicate",
                "message": (
                    "A contact with this email already exists in this "
                    "organization or earlier in this import."
                ),
            }
        )

    if phone_key and (
        phone_key in existing_phones or phone_key in seen_phones
    ):
        errors.append(
            {
                "field": "phone",
                "code": "duplicate",
                "message": (
                    "A contact with this phone number already exists in this "
                    "organization or earlier in this import."
                ),
            }
        )

    return errors


def remember_contact_keys(
    row: dict[str, Any],
    *,
    seen_emails: set[str],
    seen_phones: set[str],
) -> None:
    """Remember identifiers from a row accepted as valid."""
    email_key = normalize_email(row.get("email"))
    phone_key = normalize_phone(row.get("phone"))

    if email_key:
        seen_emails.add(email_key)

    if phone_key:
        seen_phones.add(phone_key)


__all__ = [
    "duplicate_errors",
    "load_existing_contact_keys",
    "normalize_email",
    "normalize_phone",
    "remember_contact_keys",
]