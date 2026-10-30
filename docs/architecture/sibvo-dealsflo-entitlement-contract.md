# SIBVO and Dealsflo entitlement, seat and usage contract

- **Epic:** DFR1-E12, SIBVO Identity, Entitlement, Seat & Billing Integration
- **Stories:** DFR1-004, DFR1-005, DFR1-053 (partial, see section 8)
- **Authority:** ADR-0027 (Proposed). This document records the contract as implemented on the E12 branches.
- **Related:** `docs/architecture/sibvo-dealsflo-sso-contract.md`
- **Repositories:** SIBVO (`backend/app/modules/identity/sso_router.py`, `backend/app/modules/entitlements/seat_service.py`) and Dealsflo (`backend/app/integrations/sibvo_client.py`, `backend/app/billing/entitlements.py`, `backend/app/auth/dependencies.py`, `backend/app/api/auth.py`).

## 1. Ownership

SIBVO owns identity, organizations, memberships, product membership, plans,
subscriptions, trials, entitlements, seats and billing.

Dealsflo owns its CRM records, its product roles and permissions, and its
product usage events. Dealsflo never keeps a seat counter, never grants
subscription access, and never computes SIBVO seat entitlements.

## 2. Service-to-service endpoints

Both endpoints are `POST` form requests to SIBVO under `/api/v1/sso`, authenticated with
Dealsflo's confidential client credentials (HTTP Basic). Both are read-only.

| Endpoint | Purpose | Denial |
|---|---|---|
| `/sso/introspect` | Access snapshot for a session | `{"active": false}` |
| `/sso/seat-usage` | Seat capacity for the Dealsflo product | `{"active": false}` |

A denial never says which check failed. Client authentication failure returns 401.

### 2.1 Access snapshot (`/sso/introspect`)

When access is granted, SIBVO returns `active: true` with:

| Field | Meaning |
|---|---|
| `organization_id` | SIBVO organization the snapshot authorizes |
| `product_key` | Product the snapshot authorizes (must equal Dealsflo's `SSO_DEALSFLO_PRODUCT_KEY`) |
| `subscription_status` | SIBVO subscription status |
| `plan_version_id` | Plan version in force |
| `product_role` | Product role |
| `entitlements` | `feature_key`, `enabled`, `limit_value`, `limit_unit` per feature |

Dealsflo validates every revalidation:

- The snapshot's `organization_id` must equal the session's SIBVO organization.
- The snapshot's `product_key` must equal `sso_dealsflo_product_key`.
- The entitlement shape must be valid.
- A missing or mismatched binding, or a malformed response, fails closed with 503. The stored snapshot is not replaced.
- `active: false` revokes the Dealsflo session.
- Feature checks for an attested session require the session's organization to equal the requested organization, then read only the stored snapshot.

Revalidation runs when the stored snapshot is older than
`SSO_REVALIDATION_INTERVAL_SECONDS` (default 30, range 5–300). That interval is
the maximum staleness of a revocation.

### 2.2 Seat capacity (`/sso/seat-usage`)

SIBVO returns, when the caller is an active product owner with a valid subscription:

| Field | Meaning |
|---|---|
| `organization_id`, `product_key` | Binding, checked by Dealsflo |
| `seat_limit` | Plan version's `max_seats`, or `null` when the plan is not seat-based |
| `allocated` | Active product memberships |
| `reserved` | Pending, unexpired organization invitations for the product |
| `available` | `seat_limit - allocated - reserved`, floored at 0; `null` when unlimited |

Dealsflo exposes it as `GET /api/v1/auth/sibvo-seats`. The endpoint:

- requires an attested session (404 otherwise);
- shows capacity to product owners only, using the snapshot's `product_role` (403 otherwise);
- calls SIBVO with the identifiers bound to the session, never client input;
- returns 403 when SIBVO denies, and 503 when SIBVO is unavailable or returns a malformed or mis-bound body.

The Dealsflo client (`app/integrations/sibvo_client.py`) applies a timeout, one retry for
connection errors, timeouts and server errors, normalized errors, and an
`X-Correlation-ID` per call. It does not retry 401, does not log secrets or identity values,
and rejects a body whose organization, product, counts or limit have the wrong shape.

## 3. Seat lifecycle (SIBVO is the only seat authority)

Seats are counted in SIBVO by `count_seats`: allocated = active product memberships;
reserved = pending, unexpired invitations for the product. Every operation that changes seat
usage takes the subscription row lock (`SELECT ... FOR UPDATE`), so two requests cannot both
take the last seat. A PostgreSQL concurrency test covers this, and a mutation check confirms
the test fails when the lock is removed (`backend/tests/test_seat_concurrency.py`).

Consumption points, as implemented in SIBVO:

| Lifecycle event | Seat effect | Where |
|---|---|---|
| Invitation created (product invitation) | **Reserves** a seat. Rejected when allocated + reserved ≥ limit | `reserve_invitation_seat` |
| Invitation accepted | **Allocates** the reserved seat. Rejected when allocated ≥ limit, excluding its own reservation. Idempotent if the user already holds an active seat | `allocate_invitation_seat` |
| Membership activated by an owner (direct assignment) | **Allocates**. Rejected for duplicates and when full | `assign_product_member` |
| Organization membership deactivated | **No flow exists in SIBVO.** Nothing releases the seat | Gap, see section 3.1 |
| Product membership removed | **Releases** (status `suspended`). The last active owner cannot be removed | `release_product_seat` |
| Invitation expired | Stops counting as a reservation (`expires_at` check). Status set to `expired` by the invitation service | `count_seats` |
| Invitation revoked | Stops counting as a reservation (status `revoked`) | `count_seats` |
| Subscription downgrade | **No downgrade path exists.** Plan changes come only from upgrade-request activation | Gap, see section 3.1 |
| Seat limit change | Limit is the plan version's `max_seats`. It changes only with a new version through activation | `seat_limit` |

### 3.1 Gaps that must be decided before seat enforcement is complete

1. **Organization membership deactivation has no SIBVO flow.** No code path sets
   `OrganizationMembership.status` to anything but `active`. A removed member's product seat
   is therefore never released automatically. Required: a SIBVO flow that suspends the
   product membership and releases the seat when an organization membership ends.
2. **Upgrade activation ignores pending reservations.** `activate_upgrade_request` checks
   `allocated > request.seat_count` and does not count `reserved`. A pending invitation can
   therefore exceed the purchased seat count after activation. Required: include `reserved`
   in that check, or define that acceptance re-checks the new limit (acceptance already does).
3. **Subscription downgrade is not implemented.** If a downgrade path is added, it must run
   the same allocated-plus-reserved check against the lower limit before it takes effect.

### 3.2 Dealsflo team invitations do not consume a SIBVO seat

Verified in code and in the master plan. A Dealsflo team invitation is a Dealsflo role
assignment. A user can sign in to Dealsflo only with an active SIBVO product membership
(`access_decision.py` returns `access_granted: false` with `product_membership_required`
otherwise). The seat is therefore consumed in SIBVO, when the membership is created by a
SIBVO invitation or by an owner. Accepting a Dealsflo invitation does not allocate a seat,
and Dealsflo does not call a seat-mutating SIBVO endpoint.

**Open business decision:** whether removing a user from a Dealsflo team should also end
that user's SIBVO product membership and free the seat. The workbook and master plan do not
decide this. Until they do, Dealsflo performs no seat mutation, so removing a Dealsflo team
member leaves the SIBVO seat allocated. This is a known gap, not an implemented release.

## 4. Local entitlement authority

Dealsflo's local `plan`, `subscription` and `plan_entitlement` tables can decide access only
for unattested sessions, and only when `LOCAL_ENTITLEMENT_FALLBACK_ENABLED` is `true`.

| Environment | Flag | Behaviour |
|---|---|---|
| `development` | `false` (default) | Unattested feature access denied |
| `development` | `true` | Local tables decide. Explicit opt-in |
| `test` | `true` (set by the test configuration) | Legacy request-path tests use the local tables |
| `staging` | must be `false` | Startup refused if `true`. Unattested access denied |
| `production` | must be `false` | Startup refused if `true`. Unattested access denied |

Environment detection never enables the fallback. The flag is validated when settings load
(`app/config.py`, `validate_security`).

## 5. Entitlement limits: determination and enforcement

`limit_value` and `limit_unit` are stored on `plan_version_entitlements`, validated as
non-negative, and returned in the snapshot. Determination from the code:

| Question | Finding |
|---|---|
| Does SIBVO enforce the limit? | **No.** `limit_value` is read only when it is serialized into catalog and snapshot responses. No code compares it with usage |
| Must Dealsflo enforce it? | Only for product operations whose unit and counting rule the business has agreed. None has been agreed |
| What does `limit_unit` mean? | Free text up to 40 characters, set by the plan author. No unit catalogue exists |
| Which operation consumes the limit? | None is defined. No feature key has a counting rule |
| How is usage counted? | Not counted anywhere. SIBVO has no usage-ingestion endpoint (section 6) |
| Concurrency | Not applicable until a counting rule exists |
| Limit changes and revocations | A revoked or disabled entitlement takes effect at the next revalidation (≤ the revalidation interval). A changed limit reaches Dealsflo the same way |

**Result:** Dealsflo enforces no limit, and no limit is reported as enforced. The billing page
shows a limit only as plan information (`up to N unit`). Enforcing a limit requires, for
each feature key: a unit definition agreed with the business, the Dealsflo operation that
consumes it, and a counter Dealsflo owns or SIBVO exposes. Adding enforcement without those
would invent limit semantics, which this epic does not do.

## 6. Usage reporting (DFR1-053 dependency)

**Blocked.** SIBVO has no usage-ingestion endpoint, and Dealsflo has no usage client or
ledger. Usage reconciliation is not verified and is not reported as reconciled.

Proposed event contract, for approval:

- Identity: `event_id` (UUID, client-generated), unique per organization and product.
- Idempotency: SIBVO stores `(organization_id, product_key, event_id)` and returns the
  existing result for a repeated `event_id`.
- Scope: `organization_id`, `product_key`, `user_id` (optional), `feature_key`.
- Measure: `quantity` (integer), `unit` (agreed per feature; see section 5).
- Time: `occurred_at` (timezone-aware UTC).
- Delivery: at-least-once, with bounded backoff, from the transactional outbox (ADR-0026). Only idempotent events are sent.
- Reconciliation: SIBVO compares accepted events with its meters; mismatches are recorded for review.

Depends on DFR1-017 (AI usage ledger, E13, Sprint 3) for the metering model.

## 7. Provider-independent integration boundary

- **Implemented:** one typed SIBVO client (`app/integrations/sibvo_client.py`) for every
  Dealsflo-to-SIBVO access call. It has timeouts, bounded retry for read calls, normalized
  errors (`SibvoUnavailable`, `SibvoRejected`, `SibvoInvalidResponse`), and a correlation ID.
  Its tests use a deterministic double and cover retries, errors and binding checks.
- **Not implemented:** a health-check interface, a circuit breaker, a provider-capability
  registry, and a separate audit trace of SIBVO calls. The client logs failures with the path,
  attempt and correlation ID only. Add these when a second integration needs them.
- **Test adapters:** the test double never grants access outside the test database. It
  returns only the responses a test scripts.

## 8. Story status

| Story | Status | Evidence / gap |
|---|---|---|
| DFR1-004 identity and organization contract | Implemented and tested | Snapshot binding on every revalidation; tenant binding on feature checks; client boundary. Live SIBVO not exercised |
| DFR1-005 entitlement, seat and limit contract | **Partially implemented** | Fallback removed for staging and production. Seat capacity read path implemented and tested, including concurrency. **Open:** organization-membership deactivation release (3.1-1), upgrade reservation check (3.1-2), downgrade path (3.1-3), Dealsflo team removal decision (3.2). **Limits:** not enforced, pending agreed units (section 5) |
| DFR1-053 usage reconciliation and lifecycle tests | **Blocked** | Usage contract proposed (section 6). Depends on DFR1-017, DFR1-036 and a SIBVO ingestion endpoint. Not claimed as complete |

## 9. Rollout order

1. Deploy SIBVO first. It adds `organization_id` and `product_key` to the introspection response, and it adds `/sso/seat-usage`.
2. Confirm `SSO_DEALSFLO_PRODUCT_KEY` matches SIBVO's value in every environment.
3. Deploy Dealsflo. Existing SSO sessions revalidate on their next request.
4. Dealsflo refuses to start in staging or production if `LOCAL_ENTITLEMENT_FALLBACK_ENABLED` is `true`.

Deploying Dealsflo before SIBVO fails closed: every attested session returns 503 until SIBVO
returns the binding fields. The seat page shows "temporarily unavailable" until SIBVO
exposes `/sso/seat-usage`.

## 10. Not verified

- No live SIBVO or Dealsflo environment was exercised. Verification is automated tests with a deterministic double, and a PostgreSQL run of the SIBVO suite and the seat concurrency test.
- The frontend billing page was verified by unit tests and the production build. It was not checked in a browser against a running SIBVO session.
