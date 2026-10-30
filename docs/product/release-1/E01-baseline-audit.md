# DFR1-E01 Baseline Audit (DFR1-001)

- **Epic:** DFR1-E01, Repository Baseline, Architecture & Product Foundation
- **Story:** DFR1-001, Baseline both repositories and preserve current work
- **Date:** 2026-10-30
- **Integration branch at audit:** `develop` at `3c8e705`

This audit records what was checked, the commands used, and the results. It
separates verified facts from assumptions. Results are as observed on the
machine that ran them.

## 1. Repository state

| Item | Observed state |
|---|---|
| `develop` (`origin/develop`) | `3c8e705`, the merge of PR #125 (Stage 1 redesign and MVP-07 chain) |
| Stage 1 branch `feature/redesign-stage-a-tokens-shell` | Merged through PR #125 into `develop`; remote head `b619e0b` |
| MVP-07 branch `feature/MVP-07-ui-shell-design-polish` | Merged into `develop` (ancestor check passed) |
| Dealsflo worktrees | Ten worktrees exist, one per prior MVP and the redesign branches. All were preserved and none were modified during E01 |
| E01 branch | `feature/DFR1-E01-repository-architecture-foundation`, created from `origin/develop` in its own worktree |
| SIBVO platform | Separate repository. Its backlog was not used for Release 1 planning |

## 2. Planning documents

The two authoritative Release 1 documents were located in
`C:/Users/amoun/Downloads/` and copied, unchanged, to `docs/product/release-1/`:

- `Dealsflo_Release1_Master_Architecture_and_Delivery_Plan_v2.docx`
- `Dealsflo_Release1_Jira_Backlog_v2.xlsx`

The workbook defines 15 epics, 58 stories, and 307 story points. E01 contains
four stories (DFR1-001, 002, 003, 013) totalling 13 points.

## 3. Test and quality evidence

All commands were run in the E01 worktree unless noted.

| Check | Command | Result |
|---|---|---|
| Backend test suite | `APP_ENVIRONMENT=test DATABASE_URL=...dealflow_test python -m pytest -q` | exit 0, **1216 passed**, 0 failed, 0 skipped, 65 warnings, 110 s |
| Backend suite before E01 code (audit baseline, prior run) | same command on the Stage 1 tree | 1187 passed. A prior run showed 4 failures, all from a missing `EMAIL_OUTBOX_ENCRYPTION_KEY` in the launcher. Re-run with a per-run key: all passed |
| Migration history | `alembic heads` | single head, `e5a7c1d9b2f0` (E01 migration) |
| Migrations on an empty database | `alembic upgrade head` on a reset `dealflow_test` schema | exit 0, all migrations applied |
| Migration round trip | `alembic downgrade -1` then `upgrade head` | exit 0 both ways |
| Frontend unit tests | `npm test` (Vitest) | 33 passed (4 files) |
| Frontend type check | `npx tsc -b` | exit 0 |
| Frontend lint | `npm run lint` | exit 0, 41 warnings, all pre-existing |
| Frontend build | `npm run build` | exit 0 |
| Backend lint, whole project | `ruff check app tests` | 350 pre-existing findings. Not gated in CI (see section 6) |
| Backend lint, E01 files | `ruff check` on E01 files | passes |

## 4. Existing CI configuration (before E01)

`.github/workflows/ci.yml` contained only:

- a repository structure check,
- a required-documentation check,
- a secret-file check,
- and a job named "CI Baseline" that printed a success message.

No backend tests, frontend tests, lint, type check, or build ran in CI. The
placeholder job is replaced under DFR1-013 and the E01 work (see
`docs/development/engineering-baseline.md`).

## 5. Architecture and capability inventory

Findings from reading the code. Status labels follow the workbook.

| Area | Evidence | Status |
|---|---|---|
| Modular backend structure | `backend/app/` packages, 25 routers, 50 models | Existing and verified (tests pass) |
| CRM core: contacts, leads, requirements, properties, deals, commissions, follow-ups, site visits | `backend/app/db/models/`, `backend/tests/test_*_api.py` | Existing and verified (backend tests) |
| SSO and SIBVO identity links | `docs/architecture/sibvo-dealsflo-sso-contract.md`, `api/sso.py`, `sibvo_identity_link` | Existing and verified (SSO tests) |
| Entitlement enforcement | `billing/entitlements.py` (SIBVO snapshot for attested sessions) | Existing but incomplete. A local fallback still decides non-attested sessions outside production. Staging is not production, so the fallback applies there. Recorded as an architectural conflict in the ADRs |
| Local billing tables (plan, subscription, plan_entitlement) | `db/models/plan.py`, `subscription.py`, `plan_entitlement.py` | Conflict with the SIBVO authority rule. Targeted by ADR-0027 and E12 |
| Automation rules | `automation_rules/`, `automation_execution` | Existing but incomplete (rule-based only; no versioning, visual builder, approvals or timers) |
| Email outbox | `email_outbox_messages`, `auth/email_outbox*.py` | Existing for email only |
| General transactional outbox | none before E01 | Missing before E01. Implemented under DFR1-013 |
| Notifications | `notifications/` | Existing but incomplete |
| Property matching | `requirement_match_run`, `test_property_matching*.py` | Existing but incomplete for DFR1-022 (no explanations or feedback) |
| Document upload validation | `documents/`, `test_documents_api.py` | Existing but incomplete for DFR1-035 (no extraction) |
| Channels, conversations, identity resolution, voice | none | Missing (E03, E04, E05) |
| AI gateway, agents, knowledge, budgets, predictions | none | Missing (E06, E07, E09, E13) |
| Dashboard (Today) | `dashboard/`, `test_dashboard_api.py` | Existing but incomplete for E14 |
| Frontend routes and shell | `frontend/src/app/routing/AppRouter.tsx`, `layouts/` | Existing and verified (Stage 1 browser validation) |
| Design tokens | `frontend/src/styles/tokens.css` | Existing and verified |

## 6. CI and quality gates (after E01)

Gates now enforced on every pull request to `develop`:

- repository validation (structure, required documentation including ADRs and
  the Release 1 documents, secret-file check, ADR register up to date),
- backend tests against a PostgreSQL service,
- migration check on an empty database, with a single-head assertion,
- frontend type check, lint, unit tests and production build.

Not gated, by decision:

- Whole-project Ruff. The backend has 350 pre-existing findings. CI gates Ruff
  on the E01 modules only. Reducing the baseline is tracked debt.
- Frontend lint warnings (41). They do not fail CI because the lint tool exits
  successfully on warnings.

## 7. Defects and risks found

1. **Local entitlement fallback** outside production, including staging. See ADR-0027.
2. **Password-reset tests require an encryption key** in the environment. The
   key is now provided per run in CI. Local runs need it set, see
   `docs/development/engineering-baseline.md`.
3. **Pre-existing Ruff baseline** of 350 findings.
4. **Overlapping suite runs** against the same `dealflow_test` database can
   stall. Run one suite at a time against a given test database.
5. **Provider and environment dependencies** are not provisioned. See
   `E01-environment-and-provider-matrix.md`.

## 8. Items needing validation

- Staging and production environments do not exist in this repository.
- No provider accounts were verified.
- A clean `npm ci` and `uv sync --frozen` were not run in CI on GitHub. The
  equivalent commands were run locally; first CI execution is the evidence.
