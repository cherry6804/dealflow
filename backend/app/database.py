
"""Database connection helpers for DealFlow.

Connections use the same DATABASE_URL as the main application so this
module cannot silently connect to a different hardcoded database.
"""

from collections.abc import Generator

import psycopg
from psycopg import Connection
from sqlalchemy.engine import make_url

from app.config import get_settings


def get_database_connection() -> Generator[Connection, None, None]:
    """Yield a PostgreSQL connection using the configured database URL."""
    settings = get_settings()

    # psycopg expects a standard PostgreSQL URL, not SQLAlchemy's
    # postgresql+psycopg driver-qualified URL.
    database_url = make_url(settings.database_url)
    if database_url.drivername not in {
        "postgresql",
        "postgresql+psycopg",
    }:
        raise ValueError(
            "DATABASE_URL must use postgresql or postgresql+psycopg."
        )

    psycopg_url = database_url.set(drivername="postgresql")
    connection_string = psycopg_url.render_as_string(hide_password=False)

    connection = psycopg.connect(connection_string)

    try:
        yield connection
    finally:
        connection.close()
