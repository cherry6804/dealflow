from app.config import Settings


def test_default_settings(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(
        _env_file="",
    )

    assert settings.app_name == "DealFlow API"
    assert settings.app_version == "0.1.0"
    assert settings.database_url == (
        "postgresql+psycopg://postgres@localhost:5432/dealflow"
    )


def test_database_url_can_be_overridden(monkeypatch) -> None:
    database_url = "postgresql+psycopg://test:test@localhost:5432/testdb"

    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings(
        _env_file="",
    )

    assert settings.database_url == database_url