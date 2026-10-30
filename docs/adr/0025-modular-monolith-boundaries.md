# ADR-0025: Modular Monolith Boundaries and Module Ownership

- **Status:** Proposed
- **Date:** 2026-10-30
- **Decision Owners:** DealFlow Engineering (approval pending)
- **Jira:** DFR1-002

## Context

Release 1 adds communication, AI, automation, voice and analytics on top of the existing Dealsflo CRM. The product must stay coherent and maintainable with a small team and a 30-day delivery window. Splitting into microservices now would add deployment, consistency and operational cost without measured need.

## Decision

Dealsflo remains one deployable backend (FastAPI, SQLAlchemy, PostgreSQL) and one frontend (React), organised as a modular monolith.

Each backend package under `backend/app/` owns its models, schemas, services and routes. Current modules include `leads`, `contacts`, `deals`, `properties`, `requirements`, `follow_ups`, `site_visits`, `referrals`, `documents`, `imports`, `notifications`, `automation_rules`, `billing`, `auth`, `authz`, `tenant`, `team` and `dashboard`. The `outbox` package was added under DFR1-013.

Rules:

1. Routes parse and authorize requests. Business logic lives in services.
2. A module reads another module's data through its public service functions, not by reaching into its models from unrelated code.
3. Cross-module side effects use the transactional outbox (ADR-0026), not direct calls that can leave partial state.
4. External providers sit behind adapters owned by the integration module (ADR-0028). Business modules never call provider SDKs directly.
5. A module is extracted into a separate service only with recorded evidence: an independent scaling need, a separate failure domain, or a separate release cadence.

## Alternatives Considered

- **Microservices from the start:** rejected. Too much operational cost for the current team and timeline.
- **One unstructured package:** rejected. It would make the authorization and ownership rules hard to review.

## Consequences

- Clear ownership per module and a short list of allowed cross-module paths.
- The boundaries are explicit, so a module can be moved behind the same interfaces later if evidence requires it.

## Security Considerations

Tenant scoping, permission checks and audit remain in each module's service layer (ADR-0004, ADR-0005, ADR-0006). A module boundary is not a security boundary by itself.

## Operational Considerations

One deployment, one migration history (`backend/alembic/versions`), one health surface. The quality pipeline in `.github/workflows/ci.yml` builds and tests the whole system.

## Compatibility Considerations

No change to existing API paths. New modules are additive.

## Related Decisions

ADR-0026 (outbox), ADR-0027 (SIBVO authority), ADR-0028 (channels), ADR-0029 (AI enablement), ADR-0030 (configuration).
