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
