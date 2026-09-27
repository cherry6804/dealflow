from collections.abc import Generator

import psycopg
from psycopg import Connection


def get_database_connection() -> Generator[Connection, None, None]:
    """Yield a PostgreSQL connection for the DealFlow database."""
    connection = psycopg.connect(
        "dbname=dealflow user=postgres host=localhost port=5432"
    )

    try:
        yield connection
    finally:
        connection.close()