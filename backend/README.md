# DealFlow Backend

This directory contains the DealFlow backend application.

The backend will be implemented using FastAPI and will provide the application API, business services, persistence integration, security controls, observability, and backend tests.

Backend implementation begins in Sprint S01.
# PostgreSQL test suite

Use PostgreSQL for both development and tests. The test runner derives the
isolated `dealflow_test` database from the development `DATABASE_URL`, verifies
that both databases are reachable and use the same PostgreSQL major version,
creates only `dealflow_test` if it is missing, applies Alembic migrations, and
runs pytest with `APP_ENVIRONMENT=test`. It never drops or truncates a database
and never substitutes SQLite for the CRM suite.

From this directory, run:

```powershell
uv run python scripts/test_postgres.py
```

The configured role must be allowed to create the dedicated test database on
the local PostgreSQL service. If it is not, create `dealflow_test` with an
administrator role, then run the script again.
