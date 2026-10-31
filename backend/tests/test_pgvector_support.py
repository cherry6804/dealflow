"""pgvector support: availability checks and clean failure without the extension (E06 WS1).

CI runs this file on two images, and the environment variable says which one:

* ``DEALFLOW_PGVECTOR_EXPECTED=present``: a pgvector image. The extension must be installed.
* ``DEALFLOW_PGVECTOR_EXPECTED=absent``: the official PostgreSQL image. The extension must be
  unavailable, and the guard must fail with a clear error.

Without the variable the expectation-based tests skip, so they never pass by accident.
"""

from __future__ import annotations

import os

import pytest

from app.db.pgvector import (
    PgvectorStatus,
    PgvectorUnavailableError,
    ensure_pgvector,
    pgvector_status,
)
from app.db.session import SessionLocal

EXPECTED = os.environ.get("DEALFLOW_PGVECTOR_EXPECTED")


def test_status_reads_without_writing() -> None:
    with SessionLocal() as db:
        status = pgvector_status(db.connection())
        db.rollback()

    assert isinstance(status, PgvectorStatus)
    assert isinstance(status.available, bool)
    assert isinstance(status.installed, bool)
    if status.installed:
        assert status.installed_version
    if status.available:
        assert status.default_version


@pytest.mark.skipif(EXPECTED is None, reason="DEALFLOW_PGVECTOR_EXPECTED is not set")
def test_observed_state_matches_the_expected_image() -> None:
    with SessionLocal() as db:
        status = pgvector_status(db.connection())
        db.rollback()

    if EXPECTED == "present":
        assert status.available
        assert status.installed
    elif EXPECTED == "absent":
        assert not status.available
        assert not status.installed
    else:
        pytest.fail(f"Unexpected DEALFLOW_PGVECTOR_EXPECTED value: {EXPECTED!r}")


@pytest.mark.skipif(EXPECTED != "present", reason="requires a pgvector image")
def test_guard_returns_the_installed_version_on_a_pgvector_image() -> None:
    with SessionLocal() as db:
        version = ensure_pgvector(db.connection(), create=False)
        db.rollback()

    assert version


@pytest.mark.skipif(EXPECTED != "absent", reason="requires an image without pgvector")
def test_guard_fails_cleanly_without_the_extension() -> None:
    with SessionLocal() as db:
        with pytest.raises(PgvectorUnavailableError, match="not available on this PostgreSQL server"):
            ensure_pgvector(db.connection(), create=True)
        db.rollback()


@pytest.mark.skipif(EXPECTED != "absent", reason="requires an image without pgvector")
def test_guard_failure_leaves_the_database_usable() -> None:
    with SessionLocal() as db:
        with pytest.raises(PgvectorUnavailableError):
            ensure_pgvector(db.connection(), create=True)
        db.rollback()
        still_usable = db.connection().exec_driver_sql("SELECT 1").scalar_one()
        db.rollback()

    assert still_usable == 1
