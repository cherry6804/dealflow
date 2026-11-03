"""Migration behaviour for independent audit lifecycle and immutability (WS6 WP3).

Each test builds a disposable schema inside dealflow_test and runs migrations there, so the suite's public
tables never affect the result. Checks: empty-database upgrade, preservation of an existing audit row, the
partial idempotency index, the immutability trigger and its foreign-key exception, and downgrade with
re-upgrade.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
PRE_WP3 = "f2a8c4e6b0d3"
WP3 = "b4d8f2a6c1e9"
ALEMBIC_TIMEOUT_SECONDS = 300
WP3_COLUMNS = {"outcome", "causation_id", "idempotency_key"}


def _base_url() -> str:
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    name = url.split("?")[0].rsplit("/", 1)[-1]
    assert name == "dealflow_test", f"migration tests must run against dealflow_test, not {name}"
    return url


def _schema_url(schema: str) -> str:
    separator = "&" if "?" in _base_url() else "?"
    return f"{_base_url()}{separator}options=-csearch_path%3D{schema}"


def _alembic(schema: str, *args: str) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": _schema_url(schema).replace("postgresql://", "postgresql+psycopg://", 1),
        "APP_ENVIRONMENT": "test",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=REPO_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=ALEMBIC_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stderr[-2000:]}")


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"mig_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_base_url(), autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        with psycopg.connect(_base_url(), autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA "{name}" CASCADE')


def _connect(schema: str) -> psycopg.Connection:
    return psycopg.connect(_base_url() + f"?options=-csearch_path%3D{schema}", autocommit=True)


def _user(connection: psycopg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO users (id, email, display_name, is_active, password_hash) VALUES (%s, %s, %s, true, 'x')",
        (user_id, f"{user_id}@example.test", "Audit Migration Test"),
    )
    return user_id


def _organization(connection: psycopg.Connection) -> uuid.UUID:
    organization_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO organizations (id, name, is_active) VALUES (%s, %s, true)",
        (organization_id, f"Org {organization_id}"),
    )
    return organization_id


def _audit_row(
    connection: psycopg.Connection,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str | None = None,
    action: str = "legacy.action",
) -> uuid.UUID:
    # The key is written with the row. The trigger refuses later content changes, so it cannot be set after.
    row_id = uuid.uuid4()
    # Before WP3 the column does not exist, so it is named only when a key is given.
    if key is None:
        connection.execute(
            """
            INSERT INTO audit_events (id, user_id, organization_id, event_type, action, decision,
                                      permission_key, resource_type, resource_id, correlation_id, event_metadata)
            VALUES (%s, %s, %s, 'governance', %s, 'allowed', 'governance.capabilities.manage',
                    'organization_capability', 'automation.master', 'corr-legacy', '{"legacy":true}')
            """,
            (row_id, user_id, organization_id, action),
        )
    else:
        connection.execute(
            """
            INSERT INTO audit_events (id, user_id, organization_id, event_type, action, decision,
                                      permission_key, resource_type, resource_id, correlation_id, event_metadata,
                                      idempotency_key)
            VALUES (%s, %s, %s, 'governance', %s, 'allowed', 'governance.capabilities.manage',
                    'organization_capability', 'automation.master', 'corr-legacy', '{"legacy":true}', %s)
            """,
            (row_id, user_id, organization_id, action, key),
        )
    return row_id


def _columns(connection: psycopg.Connection, schema: str) -> set[str]:
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'audit_events'",
        (schema,),
    ).fetchall()
    return {row[0] for row in rows}


def _trigger_exists(connection: psycopg.Connection, schema: str) -> bool:
    return connection.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = 'audit_events' AND t.tgname = 'audit_events_immutable')
        """,
        (schema,),
    ).fetchone()[0]


def test_an_empty_database_upgrades_to_head(schema) -> None:
    _alembic(schema, "upgrade", "head")
    with _connect(schema) as connection:
        assert WP3_COLUMNS <= _columns(connection, schema)
        assert _trigger_exists(connection, schema)


def test_an_existing_audit_row_is_preserved_unchanged(schema) -> None:
    _alembic(schema, "upgrade", PRE_WP3)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        user_id = _user(connection)
        row_id = _audit_row(connection, organization_id=organization_id, user_id=user_id)
        before = connection.execute(
            "SELECT action, decision, event_metadata, correlation_id, occurred_at FROM audit_events WHERE id = %s",
            (row_id,),
        ).fetchone()

    _alembic(schema, "upgrade", WP3)

    with _connect(schema) as connection:
        after = connection.execute(
            "SELECT action, decision, event_metadata, correlation_id, occurred_at, outcome, causation_id, "
            "idempotency_key FROM audit_events WHERE id = %s",
            (row_id,),
        ).fetchone()
    assert after[:5] == before
    assert after[5:] == (None, None, None)


def test_a_repeated_idempotency_key_is_refused_but_missing_keys_are_not(schema) -> None:
    _alembic(schema, "upgrade", WP3)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        user_id = _user(connection)
        _audit_row(connection, organization_id=organization_id, user_id=user_id, key="op-1")
        _audit_row(connection, organization_id=organization_id, user_id=user_id)
        _audit_row(connection, organization_id=organization_id, user_id=user_id)
        with pytest.raises(psycopg.errors.UniqueViolation):
            _audit_row(connection, organization_id=organization_id, user_id=user_id, key="op-1")


def test_the_trigger_refuses_changes_to_audit_content(schema) -> None:
    _alembic(schema, "upgrade", WP3)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        user_id = _user(connection)
        row_id = _audit_row(connection, organization_id=organization_id, user_id=user_id)
        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("UPDATE audit_events SET action = 'rewritten' WHERE id = %s", (row_id,))
        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("UPDATE audit_events SET event_metadata = '{}' WHERE id = %s", (row_id,))
        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("UPDATE audit_events SET organization_id = %s WHERE id = %s",
                               (uuid.uuid4(), row_id))


def test_deleting_a_user_nulls_the_reference_but_keeps_the_record(schema) -> None:
    _alembic(schema, "upgrade", WP3)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        user_id = _user(connection)
        row_id = _audit_row(connection, organization_id=organization_id, user_id=user_id)
        connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
        remaining = connection.execute(
            "SELECT user_id, action FROM audit_events WHERE id = %s", (row_id,)
        ).fetchone()
    assert remaining == (None, "legacy.action")


def test_downgrade_and_reupgrade_keep_every_row(schema) -> None:
    _alembic(schema, "upgrade", WP3)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        user_id = _user(connection)
        row_id = _audit_row(connection, organization_id=organization_id, user_id=user_id, key="keep-1")
        before = connection.execute(
            "SELECT action, decision, event_metadata FROM audit_events WHERE id = %s", (row_id,)
        ).fetchone()

    _alembic(schema, "downgrade", PRE_WP3)

    with _connect(schema) as connection:
        assert WP3_COLUMNS.isdisjoint(_columns(connection, schema))
        assert not _trigger_exists(connection, schema)
        kept = connection.execute(
            "SELECT action, decision, event_metadata FROM audit_events WHERE id = %s", (row_id,)
        ).fetchone()
    assert kept == before

    _alembic(schema, "upgrade", WP3)

    with _connect(schema) as connection:
        assert WP3_COLUMNS <= _columns(connection, schema)
        assert _trigger_exists(connection, schema)
        restored = connection.execute(
            "SELECT action, decision, event_metadata FROM audit_events WHERE id = %s", (row_id,)
        ).fetchone()
    assert restored == before
