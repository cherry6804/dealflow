"""Unit tests for read-only import row validation."""

from __future__ import annotations

import pytest

from app.imports.validation import validate_contact_rows


def test_valid_contact_row_has_no_errors() -> None:
    """Accept a row with a first name and valid optional contact details."""
    rows = [
        {
            "first_name": "Rahul",
            "last_name": "Sharma",
            "email": "rahul@example.com",
            "phone": "9876543210",
        }
    ]

    result = validate_contact_rows(rows)

    assert result["total_rows"] == 1
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 0
    assert result["errors"] == []


def test_missing_first_name_is_reported() -> None:
    """Require a non-blank first name."""
    rows = [
        {
            "first_name": "",
            "last_name": "Sharma",
            "email": "rahul@example.com",
            "phone": "9876543210",
        }
    ]

    result = validate_contact_rows(rows)

    assert result["valid_rows"] == 0
    assert result["invalid_rows"] == 1
    assert result["errors"][0]["row_number"] == 2
    assert "first_name" in result["errors"][0]["field"]
    assert result["errors"][0]["code"] == "required"


@pytest.mark.parametrize(
    "email",
    [
        "not-an-email",
        "missing-domain@",
        "@missing-local.example",
    ],
)
def test_invalid_email_is_reported(email: str) -> None:
    """Reject malformed non-empty email values."""
    rows = [{"first_name": "Rahul", "email": email}]

    result = validate_contact_rows(rows)

    assert result["invalid_rows"] == 1
    assert result["errors"][0]["row_number"] == 2
    assert result["errors"][0]["field"] == "email"
    assert result["errors"][0]["code"] == "invalid_format"


@pytest.mark.parametrize(
    "phone",
    [
        "12",
        "abc",
        "12345-abc",
    ],
)
def test_invalid_phone_is_reported(phone: str) -> None:
    """Reject phone values that do not contain a plausible phone number."""
    rows = [{"first_name": "Rahul", "phone": phone}]

    result = validate_contact_rows(rows)

    assert result["invalid_rows"] == 1
    assert result["errors"][0]["row_number"] == 2
    assert result["errors"][0]["field"] == "phone"
    assert result["errors"][0]["code"] == "invalid_format"


def test_optional_email_and_phone_can_be_blank() -> None:
    """Email and phone remain optional when empty."""
    rows = [
        {
            "first_name": "Rahul",
            "email": "",
            "phone": None,
        }
    ]

    result = validate_contact_rows(rows)

    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 0
    assert result["errors"] == []


def test_contact_name_length_limits_are_enforced() -> None:
    """Respect the existing contact model's name length limits."""
    rows = [
        {"first_name": "R" * 101},
        {"first_name": "Priya", "last_name": "S" * 101},
    ]

    result = validate_contact_rows(rows)

    assert result["total_rows"] == 2
    assert result["valid_rows"] == 0
    assert result["invalid_rows"] == 2
    assert [error["row_number"] for error in result["errors"]] == [2, 3]
    assert all(error["code"] == "max_length" for error in result["errors"])


def test_multiple_errors_are_reported_for_one_row() -> None:
    """Report all detected field errors rather than stopping at the first."""
    rows = [
        {
            "first_name": " ",
            "email": "bad-email",
            "phone": "abc",
        }
    ]

    result = validate_contact_rows(rows)

    assert result["invalid_rows"] == 1
    assert result["valid_rows"] == 0
    assert {
        (error["field"], error["code"])
        for error in result["errors"]
    } == {
        ("first_name", "required"),
        ("email", "invalid_format"),
        ("phone", "invalid_format"),
    }


def test_empty_input_returns_zero_counts() -> None:
    """Handle a file with no data rows."""
    result = validate_contact_rows([])

    assert result["total_rows"] == 0
    assert result["valid_rows"] == 0
    assert result["invalid_rows"] == 0
    assert result["errors"] == []