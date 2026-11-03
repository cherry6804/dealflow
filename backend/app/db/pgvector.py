"""pgvector availability and installation checks (E06 WS1).

The knowledge store (DFR1-016) needs the ``vector`` extension. This module only checks for it and,
when asked, installs it. It defines no tables.

A future migration that needs pgvector calls ``ensure_pgvector`` in its upgrade step. On a database
without the extension, that call raises ``PgvectorUnavailableError`` before the migration changes
anything, so the failure is clear and the rest of the schema is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

EXTENSION_NAME = "vector"


class PgvectorUnavailableError(RuntimeError):
    """pgvector cannot be used on this server or in this database."""


@dataclass(frozen=True)
class PgvectorStatus:
    """What this PostgreSQL server offers, and what this database has installed."""

    available: bool
    default_version: str | None
    trusted: bool | None
    installed: bool
    installed_version: str | None


def pgvector_status(connection: Connection) -> PgvectorStatus:
    """Read availability and installation state. This function writes nothing."""
    row = connection.execute(
        text(
            """
            SELECT
                (SELECT default_version FROM pg_available_extensions WHERE name = :name) AS default_version,
                (
                    SELECT trusted
                    FROM pg_available_extension_versions
                    WHERE name = :name
                    ORDER BY version DESC
                    LIMIT 1
                ) AS trusted,
                (SELECT extversion FROM pg_extension WHERE extname = :name) AS installed_version
            """
        ),
        {"name": EXTENSION_NAME},
    ).one()
    return PgvectorStatus(
        available=row.default_version is not None,
        default_version=row.default_version,
        trusted=row.trusted,
        installed=row.installed_version is not None,
        installed_version=row.installed_version,
    )


def ensure_pgvector(connection: Connection, *, create: bool = False) -> str:
    """Return the installed pgvector version, optionally installing the extension first.

    With ``create=False`` this only checks. With ``create=True`` it runs
    ``CREATE EXTENSION IF NOT EXISTS vector`` when the extension is available but not installed.
    Creating the extension needs the database owner or a superuser, unless the installed
    pgvector version marks the extension as trusted.

    If the extension cannot be created, the caller's transaction is aborted. Roll it back before
    reusing the connection.
    """
    status = pgvector_status(connection)
    if not status.available:
        raise PgvectorUnavailableError(
            "The pgvector extension is not available on this PostgreSQL server. "
            "Install pgvector for this PostgreSQL major version, then retry."
        )
    if not status.installed:
        if not create:
            raise PgvectorUnavailableError(
                "The pgvector extension is available but not installed in this database. "
                "A database owner or superuser must run CREATE EXTENSION vector."
            )
        try:
            connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {EXTENSION_NAME}"))
        except DBAPIError:
            raise PgvectorUnavailableError(
                "The pgvector extension could not be created. The database role lacks the "
                "required privilege. Ask a database administrator to create the extension."
            ) from None
        status = pgvector_status(connection)
        if not status.installed or status.installed_version is None:
            raise PgvectorUnavailableError("The pgvector extension is still not installed after creation.")
    return status.installed_version
