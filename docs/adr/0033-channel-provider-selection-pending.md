# ADR-0033: Channel provider selection for telephony, WhatsApp, Messenger and Instagram, and email

- **Status:** Proposed. Awaiting the owner's written provider selection.
- **Date:** 2026-11-05
- **Story:** DFR1-007
- **Related:** ADR-0028 (channel gateway architecture), ADR-0032 (provider registry and connection lifecycle), ADR-0026 (credential storage).

## Context

Release 1 needs one telephony provider for inbound and outbound calls, and channel providers for WhatsApp, Messenger, Instagram and email. ADR-0028 requires that a channel is never reported as connected, sent or placed unless the provider confirms it. ADR-0032 requires a verified connection before any external provider is used.

The provider research and comparison are in `docs/product/release-1/DFR1-007-channel-capability-matrix.md`. Key findings:

- Exotel publishes a verified inbound call webhook and retry policy, but does not document how webhooks are authenticated.
- Twilio documents `X-Twilio-Signature` (HMAC-SHA1) verification, but India voice rules restrict outbound calls to Indian numbers from non-Indian numbers, and toll-free numbers cannot be used outbound.
- Knowlarity's current developer documentation could not be verified.
- WhatsApp rates for India are in a linked INR rate card. Free service messages change on 1 October 2026.

## Decision

1. No telephony, WhatsApp, Messenger, Instagram or email provider is selected by this ADR. Selection is the owner's decision.
2. The integration design stays provider-neutral: one connection registry (ADR-0032), one verified webhook ingress (DFR1-012), one secrets boundary (DFR1-011), one AI gateway (DFR1-015), and normalised events through the outbox.
3. Each provider is added as an adapter behind a shared contract. An adapter supplies its own webhook verifier, connection probe and capability declaration. Provider payloads and statuses stay inside the adapter.
4. Provider-specific probes and verifiers are not registered until the provider is selected and a sandbox is confirmed. Nothing is marked connected or verified without a real provider check.
5. Organisation-level enablement is explicit: a capability and a connection must both be enabled, and the server enforces it.

## Consequences

- DFR1-027 (inbound call lifecycle) stays blocked until the telephony provider is chosen, webhook authentication is confirmed in writing, and a sandbox account exists.
- DFR1-011 needs no change now. A telephony provider adds a provider key, credential fields and a probe later.
- The synthetic `hmac_sha256_v1` verifier from DFR1-012 is not a provider format and is not used for any provider.

## Alternatives considered

- Select Exotel now: rejected here. Webhook authentication and sandbox access are unconfirmed.
- Select Twilio now: rejected here. The India outbound restriction must be checked against the product's outbound calling plan first.
- Use a single multi-channel aggregator: not researched in this pass.
