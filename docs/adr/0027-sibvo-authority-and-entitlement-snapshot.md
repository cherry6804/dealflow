# ADR-0027: SIBVO Authority and Entitlement Snapshot

- **Status:** Proposed
- **Date:** 2026-10-30
- **Decision Owners:** DealFlow Engineering (approval pending)
- **Jira:** DFR1-005, DFR1-053

## Context

SIBVO owns identity, organizations, memberships, the product catalogue, plans, subscriptions, entitlements, seats and billing (see `docs/architecture/sibvo-dealsflo-sso-contract.md`). Dealsflo still contains local `plan`, `subscription` and `plan_entitlement` tables. `backend/app/billing/entitlements.py` uses them as a fallback for sessions that are not SIBVO-attested. That creates a second source of truth.

## Decision

1. SIBVO is the only authority for subscriptions, plans, entitlements and seats.
2. For SSO sessions, Dealsflo stores the access snapshot SIBVO returned on each revalidation (`auth_sessions.sibvo_access`). The snapshot is a bounded cache. It may deny. It may grant only what SIBVO returned in its last answer. It expires on revalidation (`sso_revalidation_interval_seconds`).
3. A session without an attested snapshot fails closed.
4. The local plan tables must not authorize anything in `staging` or `production`. Any remaining fallback is development-only, behind an explicit flag, and is removed once no consumer depends on it.
5. Dealsflo reports usage to SIBVO through an idempotent contract. It does not bill.

This ADR states the target. E12 implements it.

## Alternatives Considered

- **Keep the local tables as an authoritative second source:** rejected.
- **Call SIBVO on every request:** rejected for latency and availability. A bounded snapshot cache is the agreed alternative.

## Consequences

- One authority per fact, with a bounded and revocable cache.
- Revocation takes effect at the next revalidation. The revalidation interval is the maximum staleness and must be stated in customer terms.
- The local tables and their reconciliation become migration debt with a defined end.

## Security Considerations

- The snapshot is read only from the server-side session, never from browser input.
- Tests must prove that a missing or expired snapshot denies access, and that one tenant's snapshot cannot apply to another tenant.

## Operational Considerations

- Staging must behave like production for entitlement decisions.
- Revocation latency is bounded by `sso_revalidation_interval_seconds`.

## Compatibility Considerations

Existing sessions have NULL snapshots and are revalidated on their next request (migration `c9f2d4a7e851`). Removing the local tables requires a data review first and is outside E01 scope.

## Related Decisions

ADR-0002 (identity), ADR-0003 (authentication), ADR-0004 (tenant context), ADR-0005 (authorization).
