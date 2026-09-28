from sqlalchemy import create_engine, text

from app.config import get_settings


def test_postgresql_connection() -> None:
    settings = get_settings()

    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
    )

    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()

        assert result == "dealflow"
    finally:
        engine.dispose()