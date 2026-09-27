from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = "postgresql+psycopg://postgres@localhost:5432/dealflow"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
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