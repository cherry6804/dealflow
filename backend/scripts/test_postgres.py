"""Prepare and run the Dealsflo test suite against isolated PostgreSQL."""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from app.config import get_settings


def postgres_url(url: URL) -> str:
    """Render a psycopg URL without exposing it in command output."""
    return url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def server_major(url: URL) -> int:
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            version = int(
                connection.execute(
                    text("SHOW server_version_num")
                ).scalar_one()
            )
        return version // 10_000
    finally:
        engine.dispose()


def ensure_test_database(source_url: URL, target_url: URL) -> None:
    """Create only the fixed test database when it is absent."""
    maintenance_url = source_url.set(database="postgres")
    with psycopg.connect(postgres_url(maintenance_url), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            ("dealflow_test",),
        ).fetchone()
        if exists is None:
            conn.execute(
                sql.SQL("CREATE DATABASE {} ").format(
                    sql.Identifier("dealflow_test")
                )
            )

    server_major(target_url)


def main() -> int:
    settings = get_settings()
    source_url = make_url(settings.database_url)

    if source_url.drivername not in {
        "postgresql",
        "postgresql+psycopg",
    }:
        raise SystemExit(
            "DATABASE_URL must be PostgreSQL; this script never falls back to SQLite."
        )
    if source_url.database != "dealflow":
        raise SystemExit(
            "DATABASE_URL must name the development database 'dealflow'; "
            "the test target is fixed to 'dealflow_test'."
        )

    test_url = source_url.set(database="dealflow_test")
    development_major = server_major(source_url)
    ensure_test_database(source_url, test_url)
    test_major = server_major(test_url)
    if development_major != test_major:
        raise SystemExit(
            "Development and test databases must use the same PostgreSQL major version."
        )

    os.environ["DATABASE_URL"] = test_url.render_as_string(
        hide_password=False
    )
    os.environ["APP_ENVIRONMENT"] = "test"

    migrations = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "..\\alembic.ini",
            "upgrade",
            "head",
        ],
        check=False,
    )
    if migrations.returncode:
        return migrations.returncode

    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        check=False,
    )
    return tests.returncode


if __name__ == "__main__":
    raise SystemExit(main())
