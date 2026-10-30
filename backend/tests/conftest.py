"""Shared pytest safety checks."""

import os

import pytest
from sqlalchemy.engine import make_url

import app.db.models  # noqa: F401  (registers every model on Base.metadata)
from app.config import get_settings
from app.db.base import Base
from app.db.session import engine


def pytest_configure() -> None:
    """Refuse to run tests against a non-test database."""
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
