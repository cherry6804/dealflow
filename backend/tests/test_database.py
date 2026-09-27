import psycopg


def test_postgresql_connection() -> None:
    with psycopg.connect(
        "dbname=dealflow user=postgres host=localhost port=5432"
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            result = cursor.fetchone()

    assert result == ("dealflow",)