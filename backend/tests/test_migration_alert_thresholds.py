"""Migration behaviour for configurable AI usage alert thresholds (WS6 WP2).

Each test builds a disposable schema inside dealflow_test, runs migrations to the WP1 head, inserts
budgets with the delivered-alert state that WP1 could have produced, runs the WP2 migration, and checks
the outcome. Columns and constraints are checked by schema name, so the suite's own public tables never
affect the result.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
PRE_WP2 = "e6b1d7a4c9f2"
WP2 = "f2a8c4e6b0d3"
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


def _organization(connection: psycopg.Connection) -> uuid.UUID:
    organization_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO organizations (id, name, is_active) VALUES (%s, %s, true)",
        (organization_id, f"Org {organization_id}"),
    )
    return organization_id


def _budget(connection: psycopg.Connection, organization_id: uuid.UUID, *, unit: str, last_alert: int) -> uuid.UUID:
    budget_id = uuid.uuid4()
    connection.execute(
        """
        INSERT INTO organization_usage_budgets
            (id, organization_id, unit, period_start, period_end, limit_quantity,
             reserved_quantity, consumed_quantity, last_alert_percent)
        VALUES (%s, %s, %s, %s, %s, 1000, 0, 0, %s)
        """,
        (budget_id, organization_id, unit, date(2026, 10, 1), date(2026, 10, 31), last_alert),
    )
    return budget_id


def _columns(connection: psycopg.Connection, schema: str, table: str) -> set[str]:
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchall()
    return {row[0] for row in rows}


def _table_exists(connection: psycopg.Connection, schema: str, table: str) -> bool:
    return connection.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s)",
        (schema, table),
    ).fetchone()[0]


def test_the_backfill_reproduces_the_delivered_thresholds_exactly(schema) -> None:
    _alembic(schema, "upgrade", PRE_WP2)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        none_yet = _budget(connection, organization_id, unit="tokens_input", last_alert=0)
        at_70 = _budget(connection, organization_id, unit="tokens_output", last_alert=70)
        at_85 = _budget(connection, organization_id, unit="audio_ms", last_alert=85)
        at_100 = _budget(connection, organization_id, unit="images", last_alert=100)

    _alembic(schema, "upgrade", WP2)

    with _connect(schema) as connection:
        rows = dict(
            connection.execute(
                "SELECT id, alerted_thresholds FROM organization_usage_budgets WHERE organization_id = %s",
                (organization_id,),
            ).fetchall()
        )
    assert rows[none_yet] == []
    assert rows[at_70] == [70]
    assert rows[at_85] == [70, 85]
    assert rows[at_100] == [70, 85, 100]


def test_the_settings_table_and_column_exist_after_upgrade_and_no_row_is_created(schema) -> None:
    _alembic(schema, "upgrade", WP2)
    with _connect(schema) as connection:
        assert _table_exists(connection, schema, "organization_usage_alert_settings")
        assert "alerted_thresholds" in _columns(connection, schema, "organization_usage_budgets")
        count = connection.execute(
            f'SELECT count(*) FROM "{schema}".organization_usage_alert_settings'
        ).fetchone()[0]
    # No existing organization is changed. Absence of a row means the defaults apply.
    assert count == 0


def test_the_settings_check_constraint_rejects_an_invalid_order(schema) -> None:
    _alembic(schema, "upgrade", WP2)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO organization_usage_alert_settings
                    (id, organization_id, threshold_low, threshold_mid, threshold_high)
                VALUES (%s, %s, 70, 70, 100)
                """,
                (uuid.uuid4(), organization_id),
            )


def test_downgrade_and_reupgrade_keep_budget_history(schema) -> None:
    _alembic(schema, "upgrade", PRE_WP2)
    with _connect(schema) as connection:
        organization_id = _organization(connection)
        budget_id = _budget(connection, organization_id, unit="tokens_output", last_alert=85)

    _alembic(schema, "upgrade", WP2)
    _alembic(schema, "downgrade", PRE_WP2)

    with _connect(schema) as connection:
        assert not _table_exists(connection, schema, "organization_usage_alert_settings")
        assert "alerted_thresholds" not in _columns(connection, schema, "organization_usage_budgets")
        # last_alert_percent is kept, so the WP1 readers see the same delivered state.
        last = connection.execute(
            "SELECT last_alert_percent FROM organization_usage_budgets WHERE id = %s", (budget_id,)
        ).fetchone()[0]
    assert last == 85

    _alembic(schema, "upgrade", WP2)

    with _connect(schema) as connection:
        assert _table_exists(connection, schema, "organization_usage_alert_settings")
        restored = connection.execute(
            "SELECT alerted_thresholds, last_alert_percent FROM organization_usage_budgets WHERE id = %s",
            (budget_id,),
        ).fetchone()
    # Re-upgrade rebuilds the covered thresholds from last_alert_percent, which is the same value.
    assert restored == ([70, 85], 85)
