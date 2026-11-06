import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from alembic import context
from app.config import get_settings
from app.db.base import Base
from app.db.migration_guard import is_migration_database_allowed

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
target_metadata = Base.metadata

# An explicit Alembic sqlalchemy.url takes precedence. Otherwise, use
# the database URL loaded by the application from its environment/.env.
configured_url = config.get_main_option("sqlalchemy.url")
database_url = (
    configured_url.strip()
    if configured_url and configured_url.strip()
    else settings.database_url
)

# Safety guard: migrations are permitted only for the application database
# and the dedicated test database. One isolated end-to-end database can be
# opted in for local verification; see app/db/migration_guard.py.
parsed_database_url = make_url(database_url)

if not is_migration_database_allowed(
    parsed_database_url,
    app_environment=settings.app_environment,
    environ=os.environ,
):
    raise RuntimeError(
        "Refusing to run Alembic against unexpected database "
        f"{parsed_database_url.database!r}. Allowed databases: "
        "'dealflow', 'dealflow_test'."
    )


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live database connection."""
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
