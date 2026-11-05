"""Validation and identity matching for lead intake (DFR1-021). Pure: no database access.

An intake payload is a small, fixed set of fields. Unknown fields are refused, and a problem message never repeats the value that
caused it, so a rejected submission cannot leak personal data into an error response or a log.

Identity matching compares normalized email and phone with existing contacts in the same organization. The rules are conservative:
a single contact matched by email is a match; a single contact matched only by phone is a match only when the name agrees too;
anything else with a candidate is ambiguous and goes to a human. The matcher never merges two existing contacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.db.models.lead import Lead
from app.imports.duplicate_detection import normalize_email, normalize_phone

INTAKE_FIELDS = frozenset({"first_name", "last_name", "email", "phone", "interest"})
MAX_NAME = 100
MAX_EMAIL = 254
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15
MAX_REFERENCE = 120
MAX_PAYLOAD_CHARACTERS = 4_096

OUTCOME_NEW_CONTACT = "new_contact"
OUTCOME_MATCHED_CONTACT = "matched_contact"
OUTCOME_MATCHED_OPEN_LEAD = "matched_open_lead"
OUTCOME_AMBIGUOUS = "ambiguous"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class IntakeCandidate:
    contact_id: str
    email_match: bool
    phone_match: bool
    name_match: bool


def _text(value: object) -> str | None:
    """Stripped text, or None when the field is absent or blank. A non-text value comes back as an empty string, which fails."""
    if value is None:
        return None
    if not isinstance(value, str):
        return ""
    return value.strip() or None


def validate_intake(raw: object) -> tuple[dict[str, Any] | None, list[str]]:
    """Return ``(normalized, problems)``. ``normalized`` is None when the payload cannot become a contact."""
    if not isinstance(raw, Mapping):
        return None, ["The submission must be an object."]
    problems: list[str] = []
    if any(key not in INTAKE_FIELDS for key in raw):
        problems.append("The submission has a field that is not part of the intake form.")

    first_name = _text(raw.get("first_name"))
    if not first_name or len(first_name) > MAX_NAME:
        problems.append("A first name of 1 to 100 characters is required.")
    last_name = _text(raw.get("last_name"))
    if last_name is not None and len(last_name) > MAX_NAME:
        problems.append("The last name must be 100 characters or fewer.")

    email = _text(raw.get("email"))
    email_ok = email is None or (len(email) <= MAX_EMAIL and bool(_EMAIL.match(email)))
    if not email_ok:
        problems.append("The email address is not valid.")

    phone_raw = _text(raw.get("phone"))
    phone_digits = normalize_phone(phone_raw) if phone_raw else None
    phone_ok = phone_raw is None or (
        phone_digits is not None and MIN_PHONE_DIGITS <= len(phone_digits) <= MAX_PHONE_DIGITS
    )
    if not phone_ok:
        problems.append("The phone number is not valid.")

    if email is None and phone_raw is None:
        problems.append("An email address or a phone number is required to identify the person.")

    interest = _text(raw.get("interest"))
    if interest is not None:
        if interest.upper() not in Lead.INTEREST_VALUES:
            problems.append("The interest must be LOW, MEDIUM or HIGH.")
        interest = interest.upper()

    if problems:
        return None, problems
    normalized: dict[str, Any] = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone_digits if phone_raw else None,
        "interest": interest,
    }
    return normalized, []


def payload_hash(normalized: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def raw_is_too_large(raw: object) -> bool:
    return len(json.dumps(raw, sort_keys=True, default=str)) > MAX_PAYLOAD_CHARACTERS


def decide_match(
    normalized: Mapping[str, Any],
    candidates: Sequence[IntakeCandidate],
) -> str:
    """Return the identity outcome for a valid submission. Writes nothing."""
    if not candidates:
        return OUTCOME_NEW_CONTACT
    if len(candidates) == 1:
        only = candidates[0]
        if only.email_match:
            return OUTCOME_MATCHED_CONTACT
        if only.phone_match and only.name_match:
            return OUTCOME_MATCHED_CONTACT
    return OUTCOME_AMBIGUOUS


def name_agrees(normalized: Mapping[str, Any], first_name: str | None, last_name: str | None) -> bool:
    given = str(normalized.get("first_name") or "").casefold()
    family = str(normalized.get("last_name") or "").casefold()
    return given == (first_name or "").casefold() and family == (last_name or "").casefold()


def email_key(normalized: Mapping[str, Any]) -> str | None:
    return normalize_email(normalized.get("email"))


def phone_key(normalized: Mapping[str, Any]) -> str | None:
    return normalized.get("phone") if normalized.get("phone") else None
