"""Verify, and optionally install, the pgvector extension for the configured database.

Used by CI and local development. It prints the observed state, never the connection string.

    uv run python -m scripts.verify_pgvector --expect present --create
    uv run python -m scripts.verify_pgvector --expect absent

Exit code 0 when the observed state matches ``--expect``. Exit code 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine

from app.config import get_settings
from app.db.pgvector import PgvectorUnavailableError, ensure_pgvector, pgvector_status


def _database_url() -> str:
    url = get_settings().database_url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect", choices=("present", "absent"), required=True)
    parser.add_argument("--create", action="store_true", help="Install the extension if it is available.")
    args = parser.parse_args(argv)

    engine = create_engine(_database_url())
    try:
        with engine.connect() as connection:
            status = pgvector_status(connection)
            print(
                f"pgvector available={status.available} default_version={status.default_version} "
                f"trusted={status.trusted} installed={status.installed} "
                f"installed_version={status.installed_version}"
            )

            if args.expect == "absent":
                matches = not status.available and not status.installed
                print("expect absent: " + ("ok" if matches else "MISMATCH"))
                return 0 if matches else 1

            try:
                version = ensure_pgvector(connection, create=args.create)
                connection.commit()
            except PgvectorUnavailableError as exc:
                connection.rollback()
                print(f"expect present: FAILED: {exc}")
                return 1
            print(f"expect present: ok (installed_version={version})")
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
