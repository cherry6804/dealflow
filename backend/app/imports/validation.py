"""Read-only validation for imported contact rows."""

from __future__ import annotations

import re
from typing import Any

MAX_FIRST_NAME_LENGTH = 100
MAX_LAST_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 320
MAX_PHONE_LENGTH = 50

_EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)

_PHONE_ALLOWED_PATTERN = re.compile(r"^[+()\-\.\s\d]+$")
_PHONE_DIGITS_PATTERN = re.compile(r"\d")


def _add_error(
    errors: list[dict[str, Any]],
    *,
    row_number: int,
    field: str,
    code: str,
    message: str,
) -> None:
    """Append a structured, source-row-specific validation error."""
    errors.append(
        {
            "row_number": row_number,
            "field": field,
            "code": code,
            "message": message,
        }
    )


def _validate_field_length(
    errors: list[dict[str, Any]],
    *,
    row_number: int,
    field: str,
    value: object,
    maximum: int,
) -> None:
    """Report values that exceed the corresponding model column length."""
    if value is not None and len(str(value)) > maximum:
        _add_error(
            errors,
            row_number=row_number,
            field=field,
            code="max_length",
            message=f"{field} must be at most {maximum} characters.",
        )


def validate_contact_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate normalized contact rows without writing to the database.

    ``rows`` must contain destination field names such as ``first_name``,
    ``last_name``, ``email``, and ``phone``. Row numbering starts at 2
    because row 1 is treated as the source header.
    """
    errors: list[dict[str, Any]] = []
    invalid_row_numbers: set[int] = set()

    for row_number, row in enumerate(rows, start=2):
        row_errors: list[dict[str, Any]] = []

        first_name = row.get("first_name")
        if first_name is None or not str(first_name).strip():
            _add_error(
                row_errors,
                row_number=row_number,
                field="first_name",
                code="required",
                message="First name is required.",
            )

        _validate_field_length(
            row_errors,
            row_number=row_number,
            field="first_name",
            value=first_name,
            maximum=MAX_FIRST_NAME_LENGTH,
        )
        _validate_field_length(
            row_errors,
            row_number=row_number,
            field="last_name",
            value=row.get("last_name"),
            maximum=MAX_LAST_NAME_LENGTH,
        )

        email_value = row.get("email")
        if email_value is not None and str(email_value).strip():
            email = str(email_value).strip()
            _validate_field_length(
                row_errors,
                row_number=row_number,
                field="email",
                value=email,
                maximum=MAX_EMAIL_LENGTH,
            )
            if (
                len(email) <= MAX_EMAIL_LENGTH
                and not _EMAIL_PATTERN.fullmatch(email)
            ):
                _add_error(
                    row_errors,
                    row_number=row_number,
                    field="email",
                    code="invalid_format",
                    message="Email address has an invalid format.",
                )

        phone_value = row.get("phone")
        if phone_value is not None and str(phone_value).strip():
            phone = str(phone_value).strip()
            _validate_field_length(
                row_errors,
                row_number=row_number,
                field="phone",
                value=phone,
                maximum=MAX_PHONE_LENGTH,
            )
            digits = _PHONE_DIGITS_PATTERN.findall(phone)
            if (
                len(phone) <= MAX_PHONE_LENGTH
                and (
                    not _PHONE_ALLOWED_PATTERN.fullmatch(phone)
                    or not 7 <= len(digits) <= 15
                )
            ):
                _add_error(
                    row_errors,
                    row_number=row_number,
                    field="phone",
                    code="invalid_format",
                    message=(
                        "Phone number must contain between 7 and 15 digits "
                        "and use only digits, spaces, +, parentheses, dots, "
                        "or hyphens."
                    ),
                )

        if row_errors:
            errors.extend(row_errors)
            invalid_row_numbers.add(row_number)

    total_rows = len(rows)
    invalid_rows = len(invalid_row_numbers)

    return {
        "total_rows": total_rows,
        "valid_rows": total_rows - invalid_rows,
        "invalid_rows": invalid_rows,
        "errors": errors,
    }


__all__ = ["validate_contact_rows"]