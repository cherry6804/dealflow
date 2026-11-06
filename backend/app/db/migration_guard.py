"""Database allowlist for Alembic migrations.

Migrations run only against the application database and the dedicated test
database. A single isolated end-to-end database can be opted in for local
verification. The opt-in is off by default and cannot widen the rule for
other names, hosts, or environments.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.engine import URL

PERMANENT_MIGRATION_DATABASES = frozenset({"dealflow", "dealflow_test"})

SSO_E2E_DATABASE = "dealflow_sso_e2e"
SSO_E2E_OPT_IN_VARIABLE = "ALEMBIC_ALLOW_SSO_E2E_DATABASE"
SSO_E2E_OPT_IN_VALUE = "1"
SSO_E2E_ENVIRONMENTS = frozenset({"development", "test"})
SSO_E2E_HOST = "127.0.0.1"


def is_migration_database_allowed(
    url: URL,
    *,
    app_environment: str,
    environ: Mapping[str, str],
) -> bool:
    """Return True when Alembic may migrate the database named by ``url``."""
    if url.database in PERMANENT_MIGRATION_DATABASES:
        return True

    return (
        environ.get(SSO_E2E_OPT_IN_VARIABLE) == SSO_E2E_OPT_IN_VALUE
        and app_environment in SSO_E2E_ENVIRONMENTS
        and url.host == SSO_E2E_HOST
        and url.database == SSO_E2E_DATABASE
    )
