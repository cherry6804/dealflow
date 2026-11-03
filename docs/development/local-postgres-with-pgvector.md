# Local PostgreSQL with pgvector

This note covers the pgvector extension for development and CI. It is part of E06 workstream WS1.
The knowledge store (DFR1-016) needs pgvector. Nothing in the repository requires it yet, so the
existing migrations and tests run with or without it.

## Image and version

- Local and CI use the same image: `pgvector/pgvector:pg16`, pinned by digest, so a tag cannot change under you.
- The major version is PostgreSQL 16, the same as the CI services before this change.
- Windows PostgreSQL 17 installs do not include pgvector. This note does not cover installing it on a host.
- To change the pinned digest, resolve the new digest from the registry, update it in `.github/workflows/ci.yml` and `infrastructure/local/docker-compose.yml` in the same change, and run the CI jobs.

## Local database with Docker

1. Start Docker Desktop (the Docker daemon must be running).
2. Choose a local password. It is never committed.
3. Start the database:

   ```bash
   POSTGRES_PASSWORD=<your-local-password> docker compose -f infrastructure/local/docker-compose.yml up -d
   ```

4. Point the backend at it. The database listens on `127.0.0.1:5433`, so it does not clash with a server on 5432:

   ```bash
   DATABASE_URL=postgresql+psycopg://postgres:<your-local-password>@127.0.0.1:5433/dealflow_test
   ```

5. Install the extension and verify it:

   ```bash
   cd backend && uv run python -m scripts.verify_pgvector --expect present --create
   ```

   The command prints the observed state and exits 0 when the extension is installed. It never prints the connection string.

6. Stop the database when you are finished:

   ```bash
   docker compose -f infrastructure/local/docker-compose.yml down
   ```

## Checks that CI runs

| Job | Image | Expectation | What it proves |
|---|---|---|---|
| Backend tests | pgvector, pinned | present | The extension installs and the guard returns its version |
| Migrations on an empty database | pgvector, pinned | present | Every migration applies with the extension present |
| Migrations and pgvector guard without pgvector | official PostgreSQL 16, pinned | absent | The migration chain does not depend on pgvector, and the guard fails cleanly |

The guard test (`tests/test_pgvector_support.py`) reads `DEALFLOW_PGVECTOR_EXPECTED`. Without the variable, the expectation tests skip, so they cannot pass by accident.

## Who may install the extension

- Creating the extension requires the database owner or a superuser, unless the installed pgvector version marks the extension as trusted for non-superuser owners.
- The trusted flag varies by version. Check it in each environment before you rely on it:

  ```sql
  SELECT name, version, trusted FROM pg_available_extension_versions WHERE name = 'vector';
  ```

- The application role should not be a superuser. In CI and local development, the `postgres` role installs the extension.
- **Production requirement (DBA):** a database administrator installs pgvector on the server for PostgreSQL 16 or the version in use, and creates the extension in each target database before any knowledge migration runs. Record the installed version. Backups restored to another server need the same extension version available there.

## What happens without the extension

- Nothing in this repository requires pgvector yet, so migrations and tests pass without it.
- A future knowledge migration will call `ensure_pgvector(connection, create=True)` in its upgrade step, from `app/db/pgvector.py`. On a server without the extension, that call raises `PgvectorUnavailableError` before any table changes. On a server where the extension is available but cannot be created, the error says that the role lacks the privilege.
- The downgrade of such a migration must not drop the extension, because other databases or future migrations may use it.

## Known limits

- The local Docker setup was written and its compose file was validated, but the container was not started in this change, because the Docker daemon was not running. The first run on a machine with Docker must confirm `verify_pgvector --expect present --create`.
- The `trusted` flag is not known for the pinned image until a container runs. The CI step prints it through the status line.
- This note does not describe production hosting. Staging and production are not provisioned.
