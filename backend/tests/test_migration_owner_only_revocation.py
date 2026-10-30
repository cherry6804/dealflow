"""Migration behaviour for owner-only grant revocation and execution rate-limit windows (E13 hardening).

Each test builds a disposable schema inside dealflow_test and never touches the public schema.
The checks: non-owner grants of owner-only keys are removed and backed up; the owner keeps them;
a downgrade restores the exact previous grants; and the rate-limit windows table is created and
dropped cleanly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.test_migration_automation_default import (
    _alembic,
    _base_url,
    _connect,
    _organization,
)

PRE = "k1a6c8e0f2b4"
REVOKE = "l2b7d9f1a3c5"
HEAD = "m3c8e0a2b4d6"
GOV_MANAGE = "governance.capabilities.manage"


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"mig_oo_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_base_url(), autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        with psycopg.connect(_base_url(), autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA "{name}" CASCADE')


def _role_id(connection: psycopg.Connection, name: str, *, system: bool = True) -> uuid.UUID:
    row = connection.execute(
        "SELECT id FROM roles WHERE name = %s AND is_system = %s LIMIT 1", (name, system)
    ).fetchone()
    assert row is not None, f"system role {name!r} must be seeded before this migration"
    return row[0]


def _org_admin_role(connection: psycopg.Connection, organization_id: uuid.UUID) -> uuid.UUID:
    """Admin is provisioned per organization (not seeded globally), so the test creates it."""
    role_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO roles (id, organization_id, name, is_system, is_active) "
        "VALUES (%s, %s, 'Admin', true, true)",
        (role_id, organization_id),
    )
    return role_id


def _permission_id(connection: psycopg.Connection, key: str) -> uuid.UUID:
    return connection.execute("SELECT id FROM permissions WHERE key = %s", (key,)).fetchone()[0]


def _grant(connection: psycopg.Connection, role_id: uuid.UUID, permission_id: uuid.UUID) -> None:
    connection.execute(
        "INSERT INTO role_permissions (id, role_id, permission_id, created_at) "
        "SELECT %s, %s, %s, now() WHERE NOT EXISTS ("
        "SELECT 1 FROM role_permissions WHERE role_id = %s AND permission_id = %s)",
        (uuid.uuid4(), role_id, permission_id, role_id, permission_id),
    )


def _grants_for(connection: psycopg.Connection, role_id: uuid.UUID, key: str) -> int:
    return connection.execute(
        "SELECT count(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
        "WHERE rp.role_id = %s AND p.key = %s",
        (role_id, key),
    ).fetchone()[0]


def _table_exists(connection: psycopg.Connection, name: str) -> bool:
    return connection.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]


def test_revocation_removes_non_owner_grants_keeps_owner_and_backs_them_up(schema: str) -> None:
    _alembic(schema, "upgrade", PRE)
    with _connect(schema) as connection:
        owner = _role_id(connection, "DealFlow Owner")
        organization_id = _organization(connection)
        admin = _org_admin_role(connection, organization_id)
        permission = _permission_id(connection, GOV_MANAGE)
        custom = uuid.uuid4()
        connection.execute(
            "INSERT INTO roles (id, organization_id, name, is_system, is_active) VALUES (%s, %s, 'Custom', false, true)",
            (custom, organization_id),
        )
        _grant(connection, owner, permission)
        _grant(connection, admin, permission)
        _grant(connection, custom, permission)

    _alembic(schema, "upgrade", REVOKE)

    with _connect(schema) as connection:
        assert _grants_for(connection, owner, GOV_MANAGE) == 1
        assert _grants_for(connection, admin, GOV_MANAGE) == 0
        assert _grants_for(connection, custom, GOV_MANAGE) == 0
        backed_up = connection.execute(
            "SELECT count(*) FROM role_permission_revocations_l2b7"
        ).fetchone()[0]
        assert backed_up == 2


def test_downgrade_restores_the_exact_previous_grants(schema: str) -> None:
    _alembic(schema, "upgrade", PRE)
    with _connect(schema) as connection:
        admin = _org_admin_role(connection, _organization(connection))
        permission = _permission_id(connection, GOV_MANAGE)
        _grant(connection, admin, permission)
    _alembic(schema, "upgrade", REVOKE)
    with _connect(schema) as connection:
        assert _grants_for(connection, admin, GOV_MANAGE) == 0

    _alembic(schema, "downgrade", PRE)

    with _connect(schema) as connection:
        assert _grants_for(connection, admin, GOV_MANAGE) == 1
        assert not _table_exists(connection, "role_permission_revocations_l2b7")


def test_rate_limit_windows_table_is_created_and_dropped_cleanly(schema: str) -> None:
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert _table_exists(connection, "execution_rate_limit_windows")
        # pg_constraint is database-wide, so scope the check to this table.
        unique_columns = connection.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid = 'execution_rate_limit_windows'::regclass "
            "AND conname = 'uq_execution_rate_limit_windows_scope' AND contype = 'u'"
        ).fetchone()[0]
        assert unique_columns == 1

    _alembic(schema, "downgrade", REVOKE)

    with _connect(schema) as connection:
        assert not _table_exists(connection, "execution_rate_limit_windows")
        assert _table_exists(connection, "role_permission_revocations_l2b7")

    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert _table_exists(connection, "execution_rate_limit_windows")
