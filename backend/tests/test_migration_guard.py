"""Tests for the Alembic migration database allowlist (app/db/migration_guard.py)."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.db.migration_guard import (
    SSO_E2E_OPT_IN_VARIABLE,
    is_migration_database_allowed,
)

OPT_IN = {SSO_E2E_OPT_IN_VARIABLE: "1"}


def _url(database: str, host: str = "127.0.0.1") -> object:
    netloc = f"[{host}]" if ":" in host else host
    return make_url(f"postgresql+psycopg://user:secret@{netloc}:5438/{database}")


@pytest.mark.parametrize("database", ["dealflow", "dealflow_test"])
@pytest.mark.parametrize("environment", ["development", "test", "staging", "production"])
def test_permanent_databases_are_always_allowed(database, environment):
    assert is_migration_database_allowed(
        _url(database, host="db.example.com"),
        app_environment=environment,
        environ={},
    )


def test_the_sso_e2e_database_is_refused_by_default():
    assert not is_migration_database_allowed(
        _url("dealflow_sso_e2e"),
        app_environment="development",
        environ={},
    )


@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_the_opt_in_requires_the_exact_value(value):
    assert not is_migration_database_allowed(
        _url("dealflow_sso_e2e"),
        app_environment="development",
        environ={SSO_E2E_OPT_IN_VARIABLE: value},
    )


@pytest.mark.parametrize("environment", ["development", "test"])
def test_the_opt_in_allows_only_the_exact_e2e_database_on_loopback(environment):
    assert is_migration_database_allowed(
        _url("dealflow_sso_e2e"),
        app_environment=environment,
        environ=OPT_IN,
    )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_opt_in_never_applies_outside_local_environments(environment):
    assert not is_migration_database_allowed(
        _url("dealflow_sso_e2e"),
        app_environment=environment,
        environ=OPT_IN,
    )


@pytest.mark.parametrize("host", ["localhost", "::1", "10.0.0.5", "db.example.com"])
def test_the_opt_in_requires_the_loopback_ip_host(host):
    assert not is_migration_database_allowed(
        _url("dealflow_sso_e2e", host=host),
        app_environment="development",
        environ=OPT_IN,
    )


@pytest.mark.parametrize(
    "database",
    ["dealflow_sso_e2e_copy", "dealflow_sso", "dealflow_sso_e2e2", "postgres", "dealflow_prod"],
)
def test_the_opt_in_never_permits_other_names(database):
    assert not is_migration_database_allowed(
        _url(database),
        app_environment="development",
        environ=OPT_IN,
    )


def test_a_url_without_a_database_name_is_refused():
    assert not is_migration_database_allowed(
        make_url("postgresql+psycopg://user@127.0.0.1:5438"),
        app_environment="development",
        environ=OPT_IN,
    )
