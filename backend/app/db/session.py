from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _session_limit_options() -> str | None:
    """Server-side session limits, so a stuck transaction cannot hold row locks indefinitely."""
    options = []
    if settings.database_statement_timeout_ms > 0:
        options.append(f"-c statement_timeout={settings.database_statement_timeout_ms}")
    if settings.database_idle_transaction_timeout_ms > 0:
        options.append(
            f"-c idle_in_transaction_session_timeout={settings.database_idle_transaction_timeout_ms}"
        )
    return " ".join(options) or None


_limit_options = _session_limit_options()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"options": _limit_options} if _limit_options else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db_session() -> Generator[Session, None, None]:
    """Yield a database session and close it after use."""
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()