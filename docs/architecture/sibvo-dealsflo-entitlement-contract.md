# SIBVO and Dealsflo entitlement, seat and usage contract

- **Epic:** DFR1-E12, SIBVO Identity, Entitlement, Seat & Billing Integration
- **Stories:** DFR1-004, DFR1-005, DFR1-053 (partial)
- **Authority:** ADR-0027 (Proposed). This document records the contract as implemented on this branch.
- **Related:** `docs/architecture/sibvo-dealsflo-sso-contract.md`

## 1. Ownership

SIBVO owns identity, organizations, memberships, product membership, plans,
subscriptions, trials, entitlements, seats and billing.

Dealsflo owns its CRM records, its product roles and permissions, and its
product usage events. Dealsflo must not grant subscription access, keep a
competing subscription authority, or compute SIBVO seat entitlements.

## 2. Access snapshot

For a SIBVO-attested session, Dealsflo calls `POST /sso/introspect` on SIBVO
with the session's subject, SIBVO session ID and SIBVO organization ID, and
authenticates with the Dealsflo client credentials.

SIBVO returns, when access is granted:

| Field | Meaning |
|---|---|
| `active` | `true` only when SIBVO grants access now |
| `organization_id` | SIBVO organization the snapshot authorizes |
| `product_key` | Product the snapshot authorizes (must equal Dealsflo's `SSO_DEALSFLO_PRODUCT_KEY`) |
| `subscription_status` | SIBVO subscription status |
| `plan_version_id` | Plan version in force |
| `product_role` | Product role |
| `entitlements` | `feature_key`, `enabled`, `limit_value`, `limit_unit` per feature |

Dealsflo validates the snapshot on every revalidation:

- The snapshot's `organization_id` must equal the session's SIBVO organization.
- The snapshot's `product_key` must equal `SSO_DEALSFLO_PRODUCT_KEY` (Dealsflo setting `sso_dealsflo_product_key`).
- The entitlement shape must be valid.
- A missing or mismatched binding, or a malformed response, fails closed with
  503. The stored snapshot is not replaced.
- `active: false` revokes the Dealsflo session.
- Feature checks for an attested session require the session's organization to
  equal the requested organization, then read only the stored snapshot.

Revalidation runs when the stored snapshot is older than
`SSO_REVALIDATION_INTERVAL_SECONDS` (default 30, range 5–300). That interval is
the maximum staleness of a revocation.

## 3. Local entitlement authority

Dealsflo's local `plan`, `subscription` and `plan_entitlement` tables can decide
access only for unattested sessions, and only when `LOCAL_ENTITLEMENT_FALLBACK_ENABLED`
is `true`.

| Environment | Flag | Behaviour |
|---|---|---|
| `development` | `false` (default) | Unattested feature access denied |
| `development` | `true` | Local tables decide. Explicit opt-in |
| `test` | `true` (set by the test configuration) | Legacy request-path tests use the local tables |
| `staging` | must be `false` | Application refuses to start if `true`. Unattested access denied |
| `production` | must be `false` | Application refuses to start if `true`. Unattested access denied |

Environment detection never enables the fallback. The flag is validated when
settings load (`app/config.py`, `validate_security`).

## 4. Seats (DFR1-005 seat requirement): contract status

**Not implemented in Dealsflo.** Dealsflo has no seat counter and makes no seat
decision. SIBVO owns seats (`app/modules/entitlements/seat_service.py`).

Gap: the existing SIBVO HTTP endpoints for product seats (product member
assign and release, `app/modules/entitlements/router.py`) are user-facing
administrative operations. Dealsflo has no service-to-service seat endpoint. The team
invitation path in Dealsflo does not call SIBVO seat allocation, and no
contract requires it to.

Required before implementation:

1. Decide whether accepting a Dealsflo team invitation consumes a SIBVO product seat.
2. If yes, SIBVO must expose a service-authenticated seat reserve, allocate and
   release operation keyed by product, organization and user, with idempotency
   keys. Dealsflo then calls it from the invitation flow.

Until then Dealsflo must not claim seat enforcement. No second seat counter is
allowed.

## 5. Usage reporting (DFR1-053 dependency): contract status

**Blocked.** SIBVO has no usage-ingestion endpoint. Dealsflo has no usage
client or ledger. Usage reconciliation is not verified and must not be
reported as reconciled.

Proposed event contract, for approval:

- Identity: `event_id` (UUID, client generated), unique per organization and product.
- Idempotency: SIBVO stores `(organization_id, product_key, event_id)` and
  returns the existing result for a repeated `event_id`.
- Scope: `organization_id`, `product_key`, `user_id` (optional), `feature_key`.
- Measure: `quantity` (integer), `unit` (for example `calls`, `records`).
- Time: `occurred_at` (timezone-aware UTC).
- Retry: at-least-once delivery with bounded backoff, from the transactional
  outbox (ADR-0026). Only idempotent events are sent.
- Reconciliation: SIBVO compares accepted events with its meters; mismatches are
  recorded for review.

Depends on DFR1-017 (AI usage ledger, E13, Sprint 3) for the metering model.

## 6. Limits

`limit_value` and `limit_unit` are returned in the snapshot. Dealsflo does not
enforce them. The SIBVO-side enforcement of those limits has not been verified
in this change. Until it is verified, Dealsflo must not treat a limit as enforced.

## 7. Story status

| Story | Status | Evidence / gap |
|---|---|---|
| DFR1-004 identity and organization contract | Implemented and tested | Snapshot binding (organization and product) on every revalidation; tenant binding on feature checks; `test_tenant_dependencies.py`, `test_e12_entitlement_authority.py` |
| DFR1-005 entitlement enforcement | Partially implemented | Staging/production fallback removed and fail-closed; snapshot tenant binding. **Seats: not implemented (section 4). Limits: not enforced (section 6).** |
| DFR1-053 usage reconciliation and lifecycle | **Blocked** | Usage contract proposed (section 5). Depends on DFR1-017 and DFR1-036 and a SIBVO ingestion endpoint. Not claimed as complete |

## 8. Rollout order

1. Deploy SIBVO first. Its introspection response now includes
   `organization_id` and `product_key`.
2. Confirm `SSO_DEALSFLO_PRODUCT_KEY` matches SIBVO's `SSO_DEALSFLO_PRODUCT_KEY`
   in every environment.
3. Deploy Dealsflo. Existing SSO sessions revalidate against the new SIBVO
   response on their next request.
4. Dealsflo refuses to start in staging or production if `LOCAL_ENTITLEMENT_FALLBACK_ENABLED` is `true`.

Deploying Dealsflo before SIBVO fails closed: every attested session returns
503 until SIBVO returns the binding fields.

## 9. Not verified

- No live SIBVO or Dealsflo environment was exercised. Verification is unit and integration tests with a deterministic introspection double.
- No provider adapter layer is implemented for SIBVO access. The introspection HTTP call remains in `app/auth/dependencies.py`. Extracting it behind a provider interface is follow-up work.
