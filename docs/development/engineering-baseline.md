# Engineering Baseline

How to run the checks that CI runs, and what each one covers.

## 1. Prerequisites

- Python 3.13 and `uv`.
- Node.js 22 and npm.
- PostgreSQL 16 for tests.

## 2. Test database

Tests run only against a database named `dealflow_test` with
`APP_ENVIRONMENT=test`. `backend/tests/conftest.py` refuses anything else.

Set these for every test run:

```bash
export APP_ENVIRONMENT=test
export DATABASE_URL="postgresql+psycopg://postgres:<password>@localhost:5432/dealflow_test"
export EMAIL_OUTBOX_ENCRYPTION_KEY="<a Fernet key>"
```

Generate a test key:

```bash
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Do not reuse a real production key. Do not commit keys.

Run one suite at a time against a given test database. Overlapping runs share
rows and locks and can stall.

## 3. Backend

```bash
cd backend
uv sync --frozen
uv run pytest -q
uv run ruff check app/outbox app/db/models/outbox_event.py tests/test_outbox.py tests/test_migrations_history.py alembic/versions/e5a7c1d9b2f0_create_outbox_events.py
```

Ruff currently reports 350 findings across the rest of the backend. Those are
tracked debt. Fix them in the module you are changing, and add the module to the
CI Ruff gate in `.github/workflows/ci.yml`.

## 4. Migrations

From the repository root, against an empty `dealflow_test` database:

```bash
uv run --project backend alembic -c alembic.ini upgrade head
uv run --project backend alembic -c alembic.ini heads
```

There must be exactly one head. `backend/tests/test_migrations_history.py`
checks the revision graph without a database.

Review every generated migration before applying it. Do not edit a migration
that has been merged to `develop`; add a new one.

## 5. Frontend

```bash
cd frontend
npm ci
npx tsc -b
npm run lint
npm test
npm run build
```

Lint exits successfully with warnings. The current count is 41, all pre-existing.

## 6. Transactional outbox

Domain events are enqueued in the caller's transaction with
`app.outbox.service.enqueue_event`. Dispatch runs in a worker:

```bash
cd backend
uv run python -m app.outbox.worker --once
uv run python -m app.outbox.worker --poll-interval 5
```

Inspect failures (operators only; payloads are not printed):

```bash
uv run python -m app.outbox.reporting --status dead_letter --limit 50
```

Handlers must be idempotent and must bound their own I/O. See ADR-0026.

## 7. Architecture decision records

`docs/adr/README.md` is the register. It is generated from each ADR's own title
and status:

```bash
python scripts/rebuild_adr_index.py
```

CI runs the same script and fails if the committed register is out of date.

## 8. Continuous integration

`.github/workflows/ci.yml` runs on pull requests to `develop` and on pushes to
feature branches:

| Job | Checks |
|---|---|
| Repository validation | Required paths and documents, ADR register up to date, no committed environment files |
| Backend tests | Dependency lock, Ruff on E01 modules, full test suite against PostgreSQL |
| Migrations on an empty database | `alembic upgrade head`, one head |
| Frontend quality gates | `npm ci`, `tsc -b`, lint, unit tests, production build |
| Quality gate | Succeeds only when all of the above succeed |

CI secrets:

- The PostgreSQL service password is a throwaway value that exists only inside
  the CI service container.
- The outbox encryption key is generated per run and masked in logs.
- No real credential is stored in the repository or in CI settings.

## 9. Secrets and files

- Never commit `.env`, `.env.local`, `.env.production`, or `.env.development`.
  CI fails if they exist.
- Put secret names in `.env.example` with empty values. Never put values there.
- Do not print secrets in logs, API responses, or test output.
