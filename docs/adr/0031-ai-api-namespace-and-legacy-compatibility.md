# ADR-0031: AI API Namespace and Legacy Route Compatibility

- **Status:** Accepted
- **Date:** 2026-10-31
- **Decision Owners:** DealFlow Engineering
- **Jira:** None. This is an E06 prerequisite (WS2) and does not change any Jira story.

## Context

Dealsflo has two merged route families that govern and expose AI-related capabilities, and both are outside a common AI namespace:

- `/api/v1/governance/…` (14 routes): capability settings, usage budgets, privacy controls and the caller's governance access. Defined in `backend/app/api/governance.py`.
- `/api/v1/provider-credentials` (4 routes): organization-scoped provider credential management. Defined in `backend/app/api/provider_credentials.py`.

The architecture plan (master document, section 11) places AI-platform APIs under `/api/v1/ai/`. The API & Integration Standards (`docs/product/Complete_Documentation_Set_v1/07_API_And_Integration_Standards.pdf`, section 2) require explicit versioning and deprecation, and say that clients should not break where possible.

No frontend route, external consumer or test outside this repository depends on the current paths, except the governance client in `frontend/src/services/governanceApi.ts`, which is in the same repository.

## Decision

1. **Canonical namespace.** All AI-platform APIs use `/api/v1/ai/`. The two existing route families move to:
   - `/api/v1/ai/governance/…` (the 14 governance routes, same method, path suffix and body), and
   - `/api/v1/ai/provider-credentials` (the 4 provider-credential routes, same method, path suffix and body).
   New AI-platform resources are added only under `/api/v1/ai/`.
2. **Legacy compatibility.** The previous paths remain available and behave identically: same status codes, response bodies, error envelope, permission checks, tenant-context handling and side effects. Legacy paths are served by the same handler functions, so behavior cannot diverge.
3. **OpenAPI visibility.** Canonical routes appear in the generated schema. Legacy routes are mounted with `include_in_schema=False` and do not appear.
4. **Deprecation and removal.**
   - Legacy routes are deprecated when this ADR is accepted and are documented as deprecated in the AI governance documentation.
   - No legacy route is removed in the change that introduces the canonical namespace.
   - Removal requires all of the following, in a separate change approved by the decision owners: the in-repository frontend uses only canonical paths, the parity suite still passes, and at least one full release cycle has passed since the canonical paths shipped.
   - Adding response headers to legacy routes (`Deprecation`, `Sunset`) is an explicit later decision. It is not part of the canonical-namespace change, because it alters responses.
5. **Security and tenant-isolation invariants.**
   - Every canonical and legacy route uses the existing dependencies: `require_permission` and `get_tenant_context`. No route in the AI namespace is unauthenticated, except those already public today.
   - Permission keys are unchanged. Owner-only keys remain owner-only (see the E13 hardening, `backend/app/authz/permissions.py`).
   - Tenant selection is unchanged: the organization comes from the verified tenant context, never from a path or body value introduced by this ADR.
   - No new endpoint may be added to the AI namespace without the same dependency pattern and a cross-tenant test.
6. **Governance of the namespace** (API & Integration Standards, section 6). Owner: DealFlow Engineering. Data scope: organization-scoped governance settings and provider-credential metadata; secret values are never returned. Permissions: as defined in the permission catalogue. Failure behavior: unchanged from the existing routes (fail closed on authorization, normalized errors). Support plan: the runbook in `docs/development/` (to be written with the owner). Deprecation strategy: section 4 above.

## Alternatives Considered

- **Rename only.** Rejected. It removes existing paths in one change, which the API standards and the approved plan do not allow without explicit versioning.
- **Keep current paths and add only new AI routes under `/api/v1/ai/`.** Rejected. It leaves two conventions for the same AI governance domain, and the approved plan places governance under the AI namespace.
- **A new version prefix (`/api/v2/`).** Rejected for this stage. It duplicates the whole API for a rename, and the standards call for explicit deprecation of specific contracts, not a version change for a namespace.

## Consequences

- Clients can migrate to the canonical paths at their own pace.
- Two paths exist for the same handler during the transition. The parity test suite must cover both.
- Legacy aliases add a small maintenance cost until they are removed.
- The OpenAPI schema lists one path per operation, so documentation and generated clients are not confused by duplicates.

## Security Considerations

- A missed dependency on an alias would be a critical defect. Both mounts share the same handler objects, which prevents this by construction, and the parity tests check unauthenticated and cross-tenant requests on both paths.
- Hiding legacy routes from the schema does not hide them from the server. It is a documentation choice, not an access control.
- Response bodies and error messages are unchanged, so no new information is disclosed.

## Operational Considerations

- Responsible operations team: DealFlow Engineering. No named on-call rota, alerting or support process is configured for these routes. Those are open items.
- No database change and no migration.
- Rollback is a revert of the change that adds the canonical mounts. Legacy paths remain in place until removal, so reverting is safe at any time before removal.
- Monitoring: request counts per path should be tracked after the canonical paths ship, so the removal decision uses evidence.

## Compatibility Considerations

- The existing paths keep working. Existing tests that use the legacy paths continue to pass unchanged.
- The frontend moves to canonical paths in the same change, because it is the only in-repository consumer.

## Related Decisions

- ADR-0027 (SIBVO authority and entitlement snapshot): tenant and entitlement behavior is unchanged.
- ADR-0029 (AI execution and disabled-by-default policy): the governance routes keep their policy semantics.
- ADR-0030 (environment and configuration standards): no configuration change.
- API & Integration Standards, sections 2 (versioning) and 6 (governance).
