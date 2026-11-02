"""Migration behaviour for AI usage reservation hardening (WS6 WP1).

Each test builds a disposable schema inside dealflow_test, runs migrations to the revision before
WP1, inserts historical usage rows with SQL, then runs the WP1 migration. The public schema is never
touched.

The decisions these tests prove:
- Historical reserved rows receive an expiry, so the reaper can recover them.
- Historical settled, released and reversed rows are unchanged.
- The new check constraints reject a reserved row without an expiry and an unknown status.
- Downgrade and re-upgrade both succeed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
PRE_WP1 = "d4e9a2c6f8b1"
WP1 = "e6b1d7a4c9f2"
ALEMBIC_TIMEOUT_SECONDS = 300


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


def _insert_usage(
    connection: psycopg.Connection,
    *,
    organization_id: uuid.UUID,
    key: str,
    status: str,
    created_at: str,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    connection.execute(
        """
        INSERT INTO ai_usage_events
            (id, organization_id, idempotency_key, unit, reserved_quantity, quantity, status,
             occurred_at, created_at, updated_at)
        VALUES (%s, %s, %s, 'tokens_output', 10, %s, %s, %s::timestamptz, %s::timestamptz, %s::timestamptz)
        """,
        (
            row_id,
            organization_id,
            key,
            None if status == "reserved" else 10,
            status,
            created_at,
            created_at,
            created_at,
        ),
    )
    return row_id


def _organization(connection: psycopg.Connection) -> uuid.UUID:
    organization_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO organizations (id, name, is_active) VALUES (%s, %s, true)",
        (organization_id, f"Org {organization_id}"),
    )
    return organization_id


WP1_COLUMNS = {"request_fingerprint", "reservation_expires_at", "released_reason"}
WP1_CONSTRAINTS = {"ck_ai_usage_events_status", "ck_ai_usage_events_reservation_expiry"}


# The helpers below are scoped to the disposable schema by name. information_schema lists every
# schema the role can see, and the suite's own create_all also builds public.ai_usage_events with
# the WP1 columns. An unscoped lookup therefore reports public's columns and says nothing about the
# schema under test.
def _columns(connection: psycopg.Connection, schema: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = 'ai_usage_events'
        """,
        (schema,),
    ).fetchall()
    return {row[0] for row in rows}


def _constraint_names(connection: psycopg.Connection, schema: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT c.conname FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = %s AND t.relname = 'ai_usage_events'
        """,
        (schema,),
    ).fetchall()
    return {row[0] for row in rows}


def test_historical_reservations_get_an_expiry_and_other_rows_are_unchanged(schema) -> None:
    _alembic(schema, "upgrade", PRE_WP1)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        reserved_id = _insert_usage(
            connection, organization_id=organization_id, key="old-reserved",
            status="reserved", created_at="2024-03-01T10:00:00+00:00",
        )
        recorded_id = _insert_usage(
            connection, organization_id=organization_id, key="old-recorded",
            status="recorded", created_at="2024-03-01T10:00:00+00:00",
        )

    _alembic(schema, "upgrade", WP1)

    with _connect(schema) as connection:
        reserved = connection.execute(
            "SELECT reservation_expires_at, created_at, request_fingerprint FROM ai_usage_events WHERE id = %s",
            (reserved_id,),
        ).fetchone()
        recorded = connection.execute(
            "SELECT reservation_expires_at, status, quantity FROM ai_usage_events WHERE id = %s",
            (recorded_id,),
        ).fetchone()

    assert reserved[0] == reserved[1] + timedelta(minutes=15)
    assert reserved[2] is None
    assert recorded == (None, "recorded", 10)


def test_wp1_adds_columns_and_constraints_that_guard_expiry_and_status(schema) -> None:
    _alembic(schema, "upgrade", WP1)

    with _connect(schema) as connection:
        assert _columns(connection, schema) >= WP1_COLUMNS
        assert _constraint_names(connection, schema) >= WP1_CONSTRAINTS

        organization_id = _organization(connection)
        # A reserved row without an expiry must be rejected by the database, not only by the code.
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO ai_usage_events
                    (id, organization_id, idempotency_key, unit, reserved_quantity, status, occurred_at)
                VALUES (%s, %s, 'bad-reserved', 'tokens_output', 5, 'reserved', now())
                """,
                (uuid.uuid4(), organization_id),
            )

    with _connect(schema) as connection:
        organization_id = _organization(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO ai_usage_events
                    (id, organization_id, idempotency_key, unit, reserved_quantity, status, occurred_at)
                VALUES (%s, %s, 'bad-status', 'tokens_output', 5, 'settled', now())
                """,
                (uuid.uuid4(), organization_id),
            )


HISTORY_QUERY = """
    SELECT idempotency_key, status, reserved_quantity, quantity, occurred_at, created_at
    FROM ai_usage_events
    WHERE organization_id = %s
    ORDER BY idempotency_key
"""


def _history(connection: psycopg.Connection, organization_id: uuid.UUID) -> list[tuple]:
    return connection.execute(HISTORY_QUERY, (organization_id,)).fetchall()


def test_downgrade_and_reupgrade_preserve_history(schema) -> None:
    _alembic(schema, "upgrade", PRE_WP1)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        _insert_usage(
            connection, organization_id=organization_id, key="cycle-recorded",
            status="recorded", created_at="2024-05-01T09:00:00+00:00",
        )
        _insert_usage(
            connection, organization_id=organization_id, key="cycle-released",
            status="released", created_at="2024-05-01T09:00:00+00:00",
        )
        _insert_usage(
            connection, organization_id=organization_id, key="cycle-open",
            status="reserved", created_at="2024-05-01T09:00:00+00:00",
        )
        before = _history(connection, organization_id)

    _alembic(schema, "upgrade", WP1)
    with _connect(schema) as connection:
        # WP1 backfills an expiry on the open reservation. That is the only change to existing data.
        assert _history(connection, organization_id) == before

    _alembic(schema, "downgrade", PRE_WP1)

    with _connect(schema) as connection:
        assert _columns(connection, schema).isdisjoint(WP1_COLUMNS)
        assert _constraint_names(connection, schema).isdisjoint(WP1_CONSTRAINTS)
        # Downgrade must keep every row exactly as it was before WP1 existed.
        assert _history(connection, organization_id) == before

    _alembic(schema, "upgrade", WP1)

    with _connect(schema) as connection:
        assert _columns(connection, schema) >= WP1_COLUMNS
        assert _constraint_names(connection, schema) >= WP1_CONSTRAINTS
        # Re-upgrade is safe: the same history is present, and the open reservation is given an expiry
        # again. Its created_at is in the past, so the reaper will release it on its next run.
        assert _history(connection, organization_id) == before
        expiry = connection.execute(
            "SELECT reservation_expires_at, created_at FROM ai_usage_events "
            "WHERE organization_id = %s AND idempotency_key = 'cycle-open'",
            (organization_id,),
        ).fetchone()
        assert expiry[0] == expiry[1] + timedelta(minutes=15)
