"""Shared pytest safety checks."""

import os

from sqlalchemy.engine import make_url

from app.config import get_settings


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