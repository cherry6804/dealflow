# ADR-0028: Communication Channel Gateway Architecture

- **Status:** Proposed
- **Date:** 2026-10-30
- **Decision Owners:** DealFlow Engineering (approval pending)
- **Jira:** DFR1-007, DFR1-011, DFR1-012, DFR1-014

## Context

Release 1 supports WhatsApp Business, Meta Messenger and Instagram, email and telephony. Each provider has different webhook signatures, send rules, template requirements and rate limits. A channel must never be reported as connected, a message as sent, or a call as placed unless the provider confirms it.

## Decision

- **Adapters.** Each provider implements a typed interface in an integration module. Business code depends on the interface, not on the provider SDK.
- **Connection registry.** `IntegrationConnection` stores provider account metadata, scopes and status. Secrets are referenced by name and never stored in plaintext in the database or logs.
- **Verified ingress.** Every webhook is checked against the provider's signature scheme before it is parsed. Raw events are stored with redaction. Deduplication uses the provider event id. Replays are rejected or de-duplicated.
- **Normalized envelope.** Provider events map to an internal envelope with a schema version, correlation id and tenant.
- **Outbound.** Sends go through the outbox (ADR-0026). Policy checks (consent, opt-out, template and messaging window) run before any provider call. A retry must not duplicate a message.
- **Honest status.** Delivery states come from provider callbacks or the provider API. The UI shows pending, sandbox, unavailable, connected and failed as separate states.

E01 records this decision and the provider capability matrix. E04 implements the gateway.

## Alternatives Considered

- **One integration class per provider with no shared interface:** rejected. It duplicates retry, redaction and status logic.
- **Store provider secrets in the database:** rejected.

## Consequences

- Adding a provider means implementing one interface, not changing core modules.
- Provider approvals (Meta business verification, WhatsApp templates, email domain verification, telephony onboarding) are external blockers, tracked in the environment and provider matrix.

## Security Considerations

- Webhook signature verification is mandatory. Unverified events are rejected and not processed.
- Secrets come from the environment or a secret manager, and are never logged or rendered.
- Redaction applies to stored raw events and to error text.

## Operational Considerations

- Provider outages are handled with bounded retries and backoff through the outbox.
- Per-provider rate limits and health snapshots are required before go-live.

## Compatibility Considerations

No existing provider integration exists to migrate. The email transport used for account mail is separate and unchanged in E01.

## Related Decisions

ADR-0026 (outbox), ADR-0029 (policy gates before any send).
