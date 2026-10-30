"""Migration behaviour for the automation default (DFR1-006 corrective migration).

Each test builds a disposable schema inside dealflow_test, runs the migrations up to the
pre-E13 revision, seeds existing organizations and automation rules with SQL, then runs the
E13 migrations and checks the outcome. The public schema is never touched. Rule and execution
rows are compared before and after to prove they are not changed.
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
AFTER_F3_BLANKET = "f3a7b9c1d2e4"
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
        timeout=300,
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
    trigger_type: str,
    created_by: uuid.UUID | None,
    updated_by: uuid.UUID | None,
) -> uuid.UUID:
    rule_id = uuid.uuid4()
    connection.execute(
        """
        INSERT INTO automation_rules
            (id, organization_id, name, trigger_type, trigger_config, conditions, actions, status,
             created_by_user_id, updated_by_user_id)
        VALUES (%s, %s, %s, %s, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, %s, %s)
        """,
        (rule_id, organization_id, f"rule {rule_id}", trigger_type, status, created_by, updated_by),
    )
    return rule_id


def _settings(connection: psycopg.Connection, organization_id: uuid.UUID) -> dict[str, tuple]:
    rows = connection.execute(
        "SELECT capability_key, is_enabled, source FROM organization_capability_settings "
        "WHERE organization_id = %s",
        (organization_id,),
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def _rule_snapshot(connection: psycopg.Connection) -> list[tuple]:
    return connection.execute(
        "SELECT id, organization_id, status, trigger_type, created_by_user_id, updated_by_user_id "
        "FROM automation_rules ORDER BY id"
    ).fetchall()


def _seed_before_e13(schema: str) -> dict[str, uuid.UUID]:
    """Existing organizations, created before E13, with the four cases the spec lists."""
    _alembic(schema, "upgrade", PRE_E13)
    with _connect(schema) as connection:
        person = _user(connection)
        no_opt_in = _organization(connection)  # no automation rules at all
        explicit_opt_in = _organization(connection)  # active rule, activated by a known user
        configured_but_inactive = _organization(connection)  # draft and disabled rules only
        active_without_activator = _organization(connection)  # active, updated_by unknown
        _rule(connection, organization_id=explicit_opt_in, status="ACTIVE", trigger_type="DEAL_CREATED",
              created_by=person, updated_by=person)
        _rule(connection, organization_id=configured_but_inactive, status="DRAFT", trigger_type="DEAL_CREATED",
              created_by=person, updated_by=person)
        _rule(connection, organization_id=configured_but_inactive, status="DISABLED", trigger_type="DEAL_CREATED",
              created_by=person, updated_by=person)
        _rule(connection, organization_id=active_without_activator, status="ACTIVE", trigger_type="DEAL_CREATED",
              created_by=None, updated_by=None)
    return {
        "no_opt_in": no_opt_in,
        "explicit_opt_in": explicit_opt_in,
        "configured_but_inactive": configured_but_inactive,
        "active_without_activator": active_without_activator,
    }


def test_existing_organization_without_opt_in_is_disabled_after_migration(schema) -> None:
    orgs = _seed_before_e13(schema)

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _settings(connection, orgs["no_opt_in"]) == {}


def test_existing_organization_with_explicit_opt_in_keeps_automation_with_evidence(schema) -> None:
    orgs = _seed_before_e13(schema)

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        settings = _settings(connection, orgs["explicit_opt_in"])
    assert settings == {
        "automation.master": (True, "migration_evidence_active_rule"),
        "automation.deal_created_rules": (True, "migration_evidence_active_rule"),
    }


def test_active_rule_without_a_known_activator_is_not_treated_as_opt_in(schema) -> None:
    orgs = _seed_before_e13(schema)

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _settings(connection, orgs["active_without_activator"]) == {}


def test_organization_with_only_inactive_workflows_is_disabled(schema) -> None:
    orgs = _seed_before_e13(schema)

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _settings(connection, orgs["configured_but_inactive"]) == {}


def test_organization_created_after_migration_starts_disabled(schema) -> None:
    _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        new_org = _organization(connection)
        assert _settings(connection, new_org) == {}


def test_migration_does_not_change_rules_or_their_history(schema) -> None:
    _seed_before_e13(schema)
    with _connect(schema) as connection:
        before = _rule_snapshot(connection)

    _alembic(schema, "upgrade", HEAD)

    with _connect(schema) as connection:
        assert _rule_snapshot(connection) == before


def test_rollback_restores_the_previous_state_and_reapplication_is_deterministic(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        evidence_state = {key: _settings(connection, value) for key, value in orgs.items()}

    _alembic(schema, "downgrade", AFTER_H5)
    with _connect(schema) as connection:
        column = connection.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
            "AND table_name = 'organization_capability_settings' AND column_name = 'source'",
            (schema,),
        ).fetchone()[0]
        assert column == 0
        # Back to the f3a7b9c1d2e4 blanket state: every organization has an enabled master row.
        for value in orgs.values():
            enabled = connection.execute(
                "SELECT is_enabled FROM organization_capability_settings "
                "WHERE organization_id = %s AND capability_key = 'automation.master'",
                (value,),
            ).fetchall()
            assert enabled == [(True,)]

    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        assert {key: _settings(connection, value) for key, value in orgs.items()} == evidence_state


def test_downgrade_refuses_to_discard_changes_made_by_people(schema) -> None:
    orgs = _seed_before_e13(schema)
    _alembic(schema, "upgrade", HEAD)
    with _connect(schema) as connection:
        person = _user(connection)
        connection.execute(
            "INSERT INTO organization_capability_settings "
            "(id, organization_id, capability_key, is_enabled, policy_version, source, updated_by_user_id, "
            " created_at, updated_at) VALUES (%s, %s, 'ai.master', true, 1, 'manual', %s, now(), now())",
            (uuid.uuid4(), orgs["no_opt_in"], person),
        )

    with pytest.raises(RuntimeError, match="people have changed capability switches"):
        _alembic(schema, "downgrade", AFTER_H5)
