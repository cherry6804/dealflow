# DFR1-E01 Environment and Provider Dependency Matrix (DFR1-003)

- **Story:** DFR1-003, Define Release 1 environment and provider dependency matrix
- **Status:** Documented. Owners, sandbox accounts and approvals are **not yet assigned or verified**. Those are external blockers.
- **Date:** 2026-10-30

Rules for this document:

- It contains no secret values, account identifiers or credentials.
- "Not verified" means no account was checked and no provider was contacted.
- Blocker dates come from the Release 1 sprint plan. Day 1 is 30 October 2026, so Day 3 is 1 November 2026.

## 1. Environments

| Environment | `APP_ENVIRONMENT` | Purpose | Database | Status |
|---|---|---|---|---|
| Local development | `development` | Developer machines | Local PostgreSQL, any database name except tests | In use |
| Automated tests | `test` | Test suite and CI | `dealflow_test` only (enforced by `tests/conftest.py`) | In use |
| Staging | `staging` | Pre-release verification | Not provisioned | **Blocked: needs owner and infrastructure decision** |
| Production | `production` | Customers | Not provisioned | **Blocked: needs owner, infrastructure and release approval** |

Required behaviour in staging and production:

- SIBVO entitlement decisions must match production. A development fallback
  must not decide authorization (ADR-0027).
- Secrets come from the environment or a secret manager, never from the
  repository (ADR-0030).

## 2. Configuration variables

Names are listed in `.env.example`. Values are never recorded in this document.

| Group | Variables | Required in | Notes |
|---|---|---|---|
| Database | `DATABASE_URL` | all | Test runs require the database name `dealflow_test` |
| CORS | `CORS_ALLOWED_ORIGINS` | all | Frontend origins |
| SIBVO SSO | `SSO_SIBVO_BASE_URL`, `SSO_DEALSFLO_CLIENT_ID`, `SSO_DEALSFLO_CLIENT_SECRET`, `SSO_DEALSFLO_REDIRECT_URI`, `SSO_HTTP_TIMEOUT_SECONDS`, `SSO_REVALIDATION_INTERVAL_SECONDS` | all | Secret: client secret. Client ID and redirect URI must match SIBVO's registration |
| Email outbox | `EMAIL_OUTBOX_ENCRYPTION_KEY` | all except where email is unused | Secret. Fernet key. Tests generate a per-run key |
| SMTP (account email) | `EMAIL_SMTP_*` | staging, production | Secret: SMTP password. Provider not verified |
| Transactional outbox | `OUTBOX_MAX_ATTEMPTS`, `OUTBOX_BASE_BACKOFF_SECONDS`, `OUTBOX_MAX_BACKOFF_SECONDS`, `OUTBOX_LEASE_SECONDS`, `OUTBOX_BATCH_SIZE` | optional | Added in E01. Bounded defaults |

Environment variable names are the upper-case form of the setting fields in
`backend/app/config.py`.

## 3. External dependency matrix

"Needed by" lists the Release 1 stories that depend on the item. Dates are
sprint-based. Where a story has no date, its sprint is given.

| # | Dependency | Needed by | Owner | Sandbox | Production | Approval needed | Fallback or test strategy | Blocker date |
|---|---|---|---|---|---|---|---|---|
| 1 | PostgreSQL | all | Engineering | Available locally and in CI | Not provisioned | Infrastructure decision | CI service container | Staging: before S2 |
| 2 | SIBVO SSO and identity API | DFR1-004, 005, 053 | SIBVO team | Not verified in this audit | Not verified | SIBVO contract sign-off | Existing contract and tests | Confirm in S1 (1 Nov 2026) |
| 3 | Redis or job queue | DFR1-013 (optional) | Infrastructure | Not provisioned | Not provisioned | Infrastructure decision | Outbox uses PostgreSQL. No Redis needed for E01 | Not required for E01 |
| 4 | Object storage (documents, recordings) | DFR1-035, 050 | Infrastructure | Not provisioned | Not provisioned | Infrastructure decision | Local storage module exists for imports | Before S5 (E10) |
| 5 | LLM provider (text, embeddings) | DFR1-015 and later | Product and Engineering | Not selected | Not selected | Provider contract, data-use terms | Provider-independent gateway with a stub for tests | Before S3 (E06) |
| 6 | Speech-to-text and text-to-speech | DFR1-028 and later | Product and Engineering | Not selected | Not selected | Provider contract, data-residency review | None | Before S4 (E05) |
| 7 | WhatsApp Business Platform | DFR1-029 | Product and Engineering | Not verified | Not verified | Meta business verification, template approval | Sandbox test number (to be confirmed) | Decision in S1 (DFR1-007) |
| 8 | Meta Messenger and Instagram messaging | DFR1-030 | Product and Engineering | Not verified | Not verified | Meta app review, page and account permissions | Only supported scopes are exposed | Decision in S1 (DFR1-007) |
| 9 | Email provider (OAuth or SMTP or IMAP) | DFR1-031 | Product and Engineering | Not selected | Not selected | Sender and domain verification | Existing SMTP settings for account mail | Decision in S1 (DFR1-007) |
| 10 | Telephony provider | DFR1-027, 044 | Product and Engineering | Not selected | Not selected | Account onboarding, number provisioning, telecom compliance (for India, DLT registration) | None | Decision in S1 (DFR1-007) |
| 11 | Secret manager | DFR1-011 and all secrets | Infrastructure | Not provisioned | Not provisioned | Infrastructure decision | Environment variables only | Before S2 (DFR1-011) |
| 12 | Monitoring and alerting | DFR1-051, 052 | Infrastructure | Not provisioned | Not provisioned | Infrastructure decision | Structured logs | Before S5 (E15) |
| 13 | Backups and restore | DFR1-052 | Infrastructure | Not provisioned | Not provisioned | Infrastructure decision | None | Before pilot (Days 16–30) |

Legend:

- **Not verified:** the item has not been checked against a live account or the official provider documentation. Nothing in this matrix claims a provider works.
- **Not provisioned:** no environment or account exists in this repository.

## 4. Decisions required

1. Assign an owner to each row. The owner column is blank until someone is named.
2. Choose the telephony, email, and messaging providers (DFR1-007, sprint S1).
3. Decide the infrastructure for staging, production, secrets, monitoring, and backups.
4. Confirm the SIBVO contract (DFR1-004, DFR1-005).
5. Decide the LLM and speech providers and their data-use terms.

## 5. Legal and compliance dependencies

These require review. They are not compliance claims.

- Telecom and messaging rules for each target market, including India DLT
  registration for SMS and voice (see the architecture document, section 13).
- Recording, transcription, and retention notices (DFR1-028, DFR1-050).
- Privacy obligations for personal data processed by AI providers.
