# Product feature and verification matrix

This matrix describes the checked-in implementation and the local checks run
for the SIBVO + Dealsflo integration. It does not certify a live deployment.

| Area | Current implementation | Local verification | Status / known gap |
| --- | --- | --- | --- |
| SIBVO identity and SSO | Authorization Code + PKCE, RS256 token validation, explicit subject and organization mappings, server-side session and entitlement checks | SIBVO and Dealsflo backend suites; focused SSO provisioning tests | Implemented locally; live cross-origin browser flow still needs QA |
| Organization onboarding | SIBVO owner can create an org; first entitled owner SSO provisions the Dealsflo tenant and owner mapping | Organization, SSO provisioning, and tenant tests | Implemented; no legacy CRM data is auto-mapped |
| Organization invitation | Owner-created, hashed, expiring single-use link; verified-email acceptance; invite screen strips token from the URL | SIBVO organization invitation API tests; SIBVO frontend production build | Manual owner handoff only; automatic email delivery held by security review |
| Product entitlements and seats | Plan/subscription access checks, role-based trial creation, owner-only product membership assignment/release and seat-cap enforcement | Entitlement, trial, and access tests | Backend implemented; seat assignment management UI remains incomplete |
| Leads and pipeline | Tenant-scoped leads, stages, ownership, status, and history | Dealsflo PostgreSQL full suite | Implemented in CRM; validate against the final deployed role matrix |
| Contacts and customer profiles | Tenant-scoped CRUD, validation, search/list operations | Dealsflo PostgreSQL full suite | Implemented |
| Properties and requirements | Inventory, property matching, customer requirements, shortlist/history | Dealsflo PostgreSQL full suite | Implemented |
| Deals and negotiations | Deals, state transitions/history, commissions, and payment milestones | Dealsflo PostgreSQL full suite | Implemented |
| Activities and follow-ups | Tenant-scoped activity timeline and follow-up records | Dealsflo PostgreSQL full suite | Implemented |
| Documents and imports | Private document handling and validated import workflows | Dealsflo PostgreSQL full suite and security tests | Implemented; production storage and malware scanning configuration must be verified operationally |
| Automation | Tenant-scoped rule configuration, validation, execution history, and supported actions | Automation rule and execution service tests in PostgreSQL suite | Implemented as workflow automation; external provider delivery depends on deployment configuration |
| AI revenue/business operations | No AI/LLM provider, model workflow, embedding/vector search, or AI feature implementation found in the application source | Source search for provider SDKs, model endpoints, embeddings, and AI modules | Not implemented; do not market as an AI-based feature yet |
| Authentication protection | SSO-bound protected access, production-disabled legacy login/signup, DB-backed login throttles, secure session handling | Auth, session, SSO, and rate-limit tests | Implemented locally; monitor and tune production thresholds |
| Tenant data isolation | Tenant context derived from authenticated session; repository/service filtering; cross-tenant rejection | Tenant authorization and PostgreSQL regression suites | Implemented in covered APIs; live security testing still required |
| Browser QA | Production TypeScript/Vite builds and ESLint completed for both frontends | `npm run build` and `npm run lint` | No interactive browser end-to-end QA completed in this run |

## Local verification evidence

- Dealsflo: `backend/scripts/test_postgres.py` ran migrations and the complete
  suite against the isolated `dealflow_test` PostgreSQL database: **1,162
  passed**. Existing PostgreSQL CRM coverage was preserved.
- SIBVO: `backend/.venv/Scripts/python.exe -m pytest -q`: **220 passed**. The
  new `c7a4e2d9b610` migration was applied to the configured local SIBVO
  PostgreSQL database and creates the organization invitations table without
  rewriting CRM or organization membership data.
- Frontends: `npm run build` and `npm run lint` were run in both frontend
  directories. Existing lint warnings are listed in the task report.

Before production, perform browser QA with configured SIBVO and Dealsflo
origins, verify mail delivery and secret-manager values, exercise seat changes
and downgraded plans, and complete an independent security review.
