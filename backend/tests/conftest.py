"""Shared pytest safety checks."""

import os

import pytest
from sqlalchemy.engine import make_url

import app.db.models  # noqa: F401  (registers every model on Base.metadata)
from app.config import get_settings
from app.db.base import Base
from app.db.session import engine

# Fixtures shared by the agent tests (DFR1-019). Registered here so test modules do not re-import them.
from tests.agents_support import keyring, world  # noqa: F401
from tests.clamd_fake import FAKE_CLAMD


def pytest_configure() -> None:
    """Refuse to run tests against a non-test database."""
    # Legacy request-path tests use the local plan tables for unattested
    # sessions. Enable the explicit test-only fallback here. Tests that
    # verify denial turn it off with monkeypatch.
    os.environ.setdefault("LOCAL_ENTITLEMENT_FALLBACK_ENABLED", "true")
    # Uploads are malware-scanned. Tests use a local stand-in clamd daemon that speaks the real protocol, so the scanner
    # client runs for real. It is not a bypass: an upload still needs a CLEAN verdict.
    os.environ["CLAMAV_HOST"] = "127.0.0.1"
    os.environ["CLAMAV_PORT"] = str(FAKE_CLAMD.start())
    # Settings are cached once per process; drop any copy read at import time.
    get_settings.cache_clear()
    settings = get_settings()
    database_url = os.environ.get("DATABASE_URL") or settings.database_url
    database_name = make_url(database_url).database

    if database_name != "dealflow_test":
        raise RuntimeError(
            "Unsafe pytest database configuration. "
            "Tests must use 'dealflow_test'; "
            f"configured database is {database_name!r}."
        )

    if settings.app_environment != "test":
        raise RuntimeError(
            "Unsafe pytest environment. "
            "Set APP_ENVIRONMENT=test before running tests."
        )


@pytest.fixture(scope="session", autouse=True)
def create_test_schema() -> None:
    """Create every model table before the first test runs.

    Several test modules assume tables already exist, and some modules drop all
    tables. A fresh database, such as a CI service container, starts empty, so
    the suite must create the schema itself. create_all is idempotent and never
    drops existing tables.
    """
    Base.metadata.create_all(bind=engine)
