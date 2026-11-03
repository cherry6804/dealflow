"""Migration behaviour for encrypted provider credentials (DFR1-011 subset).

Each test builds a disposable schema inside dealflow_test and never touches the public schema.
The checks: the table, its constraints and partial unique index are created; the owner gets the
provider credential permissions; downgrade refuses while encrypted credentials exist; and the
migration can be applied again after a clean downgrade.
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

PRE = "i7f2c9d4e1a8"
HEAD = "k1a6c8e0f2b4"


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"mig_pc_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_base_url(), autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        with psycopg.connect(_base_url(), autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA "{name}" CASCADE')


def _insert_active_credential(connection: psycopg.Connection, organization_id: uuid.UUID) -> uuid.UUID:
    credential_id = uuid.uuid4()
    connection.execute(
        """
        INSERT INTO provider_credentials
            (id, organization_id, provider_key, label, status, version, ciphertext,
             encryption_key_id, encryption_algorithm)
        VALUES (%s, %s, 'openai', 'Primary', 'active', 1, 'Y2lwaGVy', 'test-v1', 'aes-256-gcm')
        """,
        (credential_id, organization_id),
    )
    return credential_id


def _table_exists(connection: psycopg.Connection) -> bool:
    return connection.execute(
        "SELECT to_regclass(%s) IS NOT NULL", ("provider_credentials",)
    ).fetchone()[0]


def test_upgrade_creates_constrained_table_index_and_permissions(schema: str) -> None:
    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _table_exists(connection)
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'provider_credentials'"
            ).fetchall()
        }
        assert {"ciphertext", "encryption_key_id", "encryption_algorithm", "version"} <= columns

        index_definition = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'provider_credentials' "
            "AND indexname = 'uq_provider_credentials_active_provider'"
        ).fetchone()[0]
        assert "UNIQUE" in index_definition and "WHERE" in index_definition

        keys = {
            row[0]
            for row in connection.execute(
                "SELECT key FROM permissions WHERE key LIKE 'provider_credentials.%'"
            ).fetchall()
        }
        assert keys == {"provider_credentials.read", "provider_credentials.manage"}


def test_check_constraints_keep_active_rows_encrypted_and_revoked_rows_empty(schema: str) -> None:
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO provider_credentials (id, organization_id, provider_key, label, status, version) "
                "VALUES (%s, %s, 'openai', 'x', 'active', 1)",
                (uuid.uuid4(), organization_id),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO provider_credentials (id, organization_id, provider_key, label, status, version, "
                "ciphertext, encryption_key_id, encryption_algorithm) "
                "VALUES (%s, %s, 'openai', 'x', 'revoked', 1, 'Y2lwaGVy', 'k', 'aes-256-gcm')",
                (uuid.uuid4(), organization_id),
            )


def test_owner_role_receives_the_provider_credential_permissions(schema: str) -> None:
    _alembic(schema, "upgrade", PRE)
    with _connect(schema) as connection:
        owner_roles = connection.execute(
            "SELECT count(*) FROM roles WHERE name = 'DealFlow Owner' AND is_system = true"
        ).fetchone()[0]
    assert owner_roles == 1, "the system owner role must be seeded before this migration"

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        granted = {
            row[0]
            for row in connection.execute(
                "SELECT p.key FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id JOIN permissions p ON p.id = rp.permission_id "
                "WHERE r.name = 'DealFlow Owner' AND p.key LIKE 'provider_credentials.%'"
            ).fetchall()
        }
    assert granted == {"provider_credentials.read", "provider_credentials.manage"}


def test_downgrade_refuses_while_encrypted_credentials_exist(schema: str) -> None:
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        _insert_active_credential(connection, organization_id)

    with pytest.raises(RuntimeError, match="encrypted provider credentials exist"):
        _alembic(schema, "downgrade", PRE)

    with _connect(schema) as connection:
        assert _table_exists(connection)


def test_clean_downgrade_then_reapply_restores_the_table(schema: str) -> None:
    _alembic(schema, "upgrade", HEAD)
    _alembic(schema, "downgrade", PRE)
    with _connect(schema) as connection:
        assert not _table_exists(connection)
        leftovers = connection.execute(
            "SELECT count(*) FROM permissions WHERE key LIKE 'provider_credentials.%'"
        ).fetchone()[0]
    assert leftovers == 0

    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert _table_exists(connection)
        organization_id = _organization(connection)
        _insert_active_credential(connection, organization_id)
        assert connection.execute("SELECT count(*) FROM provider_credentials").fetchone()[0] == 1
