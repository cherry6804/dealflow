"""Outbox failure text must never carry personal data (DFR1-050 log review)."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.outbox.service import _describe_error


def test_database_error_text_is_withheld_because_it_echoes_row_values() -> None:
    error = IntegrityError(
        "INSERT INTO contacts (email) VALUES (%(email)s)",
        {"email": "private.person@example.test"},
        Exception('Key (email)=(private.person@example.test) already exists.'),
    )

    described = _describe_error(error)

    assert "private.person@example.test" not in described
    assert described.startswith("IntegrityError:")


def test_ordinary_handler_errors_keep_their_message_for_operators() -> None:
    assert _describe_error(RuntimeError("provider timed out")) == "RuntimeError: provider timed out"


def test_the_stored_message_is_bounded_and_single_line() -> None:
    described = _describe_error(RuntimeError("line one\nline two " + "x" * 2000))

    assert "\n" not in described
    assert len(described) <= 500


def test_email_addresses_and_phone_numbers_are_replaced_in_ordinary_errors() -> None:
    described = _describe_error(ValueError("owner private.person@example.test rejected, call +91 98765 43210"))

    assert "private.person" not in described
    assert "98765" not in described
    assert "[email]" in described and "[phone]" in described


def test_dates_are_not_mistaken_for_phone_numbers() -> None:
    described = _describe_error(RuntimeError("window closed on 2026-11-06 at 21:35"))

    assert "2026-11-06" in described
