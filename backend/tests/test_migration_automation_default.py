"""Migration behaviour for the automation default (decision 1, DFR1-006).

Each test builds a disposable schema inside dealflow_test, runs the migrations up to the
pre-E13 revision, seeds existing organizations, rules and execution history with SQL, then runs
the E13 migrations and checks the outcome. The public schema is never touched.

The decision these tests prove: no existing organization is enabled by a migration. Rules,
configurations and execution history are preserved, and nothing executes during migration.
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
PRE_E13 = "a1e2c3d4f5b6"
AFTER_H5 = "h5c9d1e3f6a7"
HEAD = "i7f2c9d4e1a8"


def _base_url() -> str:
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    name = url.split("?")[0].rsplit("/", 1)[-1]
    assert name == "dealflow_test", f"migration tests must run against dealflow_test, not {name}"
    return url


def _schema_url(schema: str) -> str:
    separator = "&" if "?" in _base_url() else "?"
    return f"{_base_url()}{separator}options=-csearch_path%3D{schema}"


ALEMBIC_TIMEOUT_SECONDS = 300
ALEMBIC_ATTEMPTS = 2


def _alembic(schema: str, *args: str) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": _schema_url(schema).replace("postgresql://", "postgresql+psycopg://", 1),
        "APP_ENVIRONMENT": "test",
    }
    for attempt in range(ALEMBIC_ATTEMPTS):
        try:
            # Each attempt keeps the full timeout. The standard library measures the deadline with
            # time.monotonic(). A machine suspend can advance that clock past the deadline while the
            # child is healthy, which reports a timeout with a negative remaining time. Migrations run
            # in transactions, so a killed attempt rolls back and a second attempt is safe. A genuine
            # hang still fails on the final attempt.
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
                cwd=REPO_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=ALEMBIC_TIMEOUT_SECONDS,
                check=False,
            )
            break
        except subprocess.TimeoutExpired:
            if attempt == ALEMBIC_ATTEMPTS - 1:
                raise
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
        (user_id, f"{user_id}@example.test", "Migration Test"),
    )
    return user_id


def _organization(connection: psycopg.Connection) -> uuid.UUID:
    organization_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO organizations (id, name, is_active) VALUES (%s, %s, true)",
        (organization_id, f"Org {organization_id}"),
    )
    return organization_id


def _rule(
    connection: psycopg.Connection,
    *,
    organization_id: uuid.UUID,
    status: str,
    created_by: uuid.UUID | None,
    updated_by: uuid.UUID | None,
) -> uuid.UUID:
    rule_id = uuid.uuid4()
    connection.execute(
        """
        INSERT INTO automation_rules
            (id, organization_id, name, trigger_type, trigger_config, conditions, actions, status,
             created_by_user_id, updated_by_user_id)
        VALUES (%s, %s, %s, 'DEAL_CREATED', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, %s, %s)
        """,
        (rule_id, organization_id, f"rule {rule_id}", status, created_by, updated_by),
    )
    return rule_id


def _execution(connection: psycopg.Connection, *, organization_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    connection.execute(
        """
        INSERT INTO automation_executions
            (id, organization_id, rule_id, event_type, event_id, action_results)
        VALUES (%s, %s, %s, 'DEAL_CREATED', %s, '[]'::jsonb)
        """,
        (uuid.uuid4(), organization_id, rule_id, uuid.uuid4()),
    )


def _automation_state(connection: psycopg.Connection, organization_id: uuid.UUID) -> list[tuple]:
    return connection.execute(
        "SELECT capability_key, is_enabled FROM organization_capability_settings "
        "WHERE organization_id = %s ORDER BY capability_key",
        (organization_id,),
    ).fetchall()


def _snapshot(connection: psycopg.Connection) -> dict[str, list]:
    """Everything the migration must not change: rules, executions and notifications."""
    return {
        "rules": connection.execute(
            "SELECT id, organization_id, status, trigger_type, created_by_user_id, updated_by_user_id, "
            "trigger_config::text, conditions::text, actions::text FROM automation_rules ORDER BY id"
        ).fetchall(),
        "executions": connection.execute(
            "SELECT id, rule_id FROM automation_executions ORDER BY id"
        ).fetchall(),
        "notifications": connection.execute("SELECT count(*) FROM notifications").fetchall(),
    }


def _seed_before_e13(schema: str) -> dict[str, uuid.UUID]:
    """Existing organizations with every case the decision lists."""
    _alembic(schema, "upgrade", PRE_E13)
    with _connect(schema) as connection:
        person = _user(connection)
        active = _organization(connection)
        draft = _organization(connection)
        disabled = _organization(connection)
        no_rules = _organization(connection)
        with_history = _organization(connection)
        active_rule = _rule(connection, organization_id=active, status="ACTIVE",
                            created_by=person, updated_by=person)
        _rule(connection, organization_id=draft, status="DRAFT", created_by=person, updated_by=person)
        _rule(connection, organization_id=disabled, status="DISABLED", created_by=person, updated_by=person)
        history_rule = _rule(connection, organization_id=with_history, status="ACTIVE",
                             created_by=person, updated_by=person)
        _execution(connection, organization_id=with_history, rule_id=history_rule)
        _execution(connection, organization_id=active, rule_id=active_rule)
    return {
        "active": active,
        "draft": draft,
        "disabled": disabled,
        "no_rules": no_rules,
        "with_history": with_history,
    }


def test_existing_organization_with_active_rule_starts_disabled(schema) -> None:
    orgs = _seed_before_e13(schema)

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _automation_state(connection, orgs["active"]) == []


def test_existing_organization_with_draft_rule_starts_disabled(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert _automation_state(connection, orgs["draft"]) == []


def test_existing_organization_with_disabled_rule_starts_disabled(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert _automation_state(connection, orgs["disabled"]) == []


def test_existing_organization_with_no_rules_starts_disabled(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert _automation_state(connection, orgs["no_rules"]) == []


def test_organization_with_historical_executions_starts_disabled_and_keeps_history(schema) -> None:
    orgs = _seed_before_e13(schema)
    with _connect(schema) as connection:
        history_before = connection.execute(
            "SELECT id, rule_id FROM automation_executions WHERE organization_id = %s ORDER BY id",
            (orgs["with_history"],),
        ).fetchall()
    assert history_before, "the seed must contain execution history"

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _automation_state(connection, orgs["with_history"]) == []
        history_after = connection.execute(
            "SELECT id, rule_id FROM automation_executions WHERE organization_id = %s ORDER BY id",
            (orgs["with_history"],),
        ).fetchall()
    assert history_after == history_before


def test_organization_created_after_migration_starts_disabled(schema) -> None:
    _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        new_org = _organization(connection)
        assert _automation_state(connection, new_org) == []


def test_explicit_opt_in_after_migration_is_recorded_with_its_actor(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        admin = _user(connection)
        connection.execute(
            "INSERT INTO organization_capability_settings "
            "(id, organization_id, capability_key, is_enabled, policy_version, source, updated_by_user_id, "
            " created_at, updated_at) VALUES (%s, %s, 'automation.master', true, 1, 'manual', %s, now(), now())",
            (uuid.uuid4(), orgs["active"], admin),
        )
        row = connection.execute(
            "SELECT is_enabled, updated_by_user_id, source FROM organization_capability_settings "
            "WHERE organization_id = %s AND capability_key = 'automation.master'",
            (orgs["active"],),
        ).fetchone()
    assert row == (True, admin, "manual")


def test_migration_changes_no_rule_execution_or_notification(schema) -> None:
    _seed_before_e13(schema)
    with _connect(schema) as connection:
        before = _snapshot(connection)
    assert before["executions"], "the seed must contain execution history"

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _snapshot(connection) == before


def test_rollback_does_not_re_enable_anything_and_reapplication_stays_disabled(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        before_rollback = _snapshot(connection)

    _alembic(schema, "downgrade", AFTER_H5)
    with _connect(schema) as connection:
        column_count = connection.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'organization_capability_settings' AND column_name = 'source'",
            (schema,),
        ).fetchone()[0]
        assert column_count == 0
        for value in orgs.values():
            assert _automation_state(connection, value) == [], "rollback must not re-enable automation"
        assert _snapshot(connection) == before_rollback

    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        for value in orgs.values():
            assert _automation_state(connection, value) == []
        assert _snapshot(connection) == before_rollback


def test_rollback_refuses_to_discard_changes_made_by_people(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        admin = _user(connection)
        connection.execute(
            "INSERT INTO organization_capability_settings "
            "(id, organization_id, capability_key, is_enabled, policy_version, source, updated_by_user_id, "
            " created_at, updated_at) VALUES (%s, %s, 'ai.master', true, 1, 'manual', %s, now(), now())",
            (uuid.uuid4(), orgs["no_rules"], admin),
        )

    with pytest.raises(RuntimeError, match="people have changed capability switches"):
        _alembic(schema, "downgrade", AFTER_H5)
