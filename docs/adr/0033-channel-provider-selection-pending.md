# ADR-0033: Release 1 communication provider strategy

- **Status:** Accepted (architectural selection). Provider accounts, credentials, sandbox access, API permissions and live integrations are **not verified** by this decision.
- **Date proposed:** 2026-11-05. **Accepted:** on owner approval, recorded in the DFR1-007 pull request.
- **Story:** DFR1-007.
- **Related:** ADR-0028 (channel gateway architecture), ADR-0032 (provider registry and connection lifecycle), ADR-0026 (credential storage), DFR1-011, DFR1-012, DFR1-015, DFR1-027 to DFR1-031.
- **Evidence:** `docs/product/release-1/DFR1-007-channel-capability-matrix.md`.

## Context

Release 1 needs telephony for India and for supported international countries, WhatsApp, Messenger and Instagram messaging, and email. ADR-0028 requires that a channel is never reported as connected, a message as sent, or a call as placed unless the provider confirms it. ADR-0032 requires a verified connection before any external provider is used.

## Decisions

1. **India telephony: Exotel, primary.**
2. **International telephony: Twilio, primary for supported countries and calling directions.** Each target country and direction is validated before it is enabled.
3. **WhatsApp: Meta WhatsApp Business Cloud API, direct.** No BSP at launch.
4. **Messenger and Instagram: official Meta APIs.** Release 1 P1, not a launch blocker.
5. **Email: Amazon SES, initial transport,** subject to validating inbound email, threading and attachments.
6. **Call recording: supported in Release 1, disabled by default.** Enabled only under consent, privacy, retention and organisation policy (matrix section 8).

## Conditions (each must be met before the dependent work starts)

- **Exotel:** written webhook authentication or signature documentation; sandbox account and test number; inbound calling API; answer and bridge behaviour; human transfer behaviour; AI streaming capability and protocol; number provisioning and regulatory requirements; pricing and concurrency limits.
- **Twilio:** for every target country and calling direction, confirmed number availability, regulatory bundle, and outbound and inbound rules.
- **WhatsApp and Meta:** business verification, app review and permissions, webhook verification, templates, account ownership and messaging policies.
- **Messenger and Instagram:** App Review for Advanced Access (if used beyond the Dealsflo-owned Page), page and account permissions, messaging window rules, webhook verification.
- **SES:** sender and domain identity verified; outbound delivery confirmed; inbound receiving rule configured; threading and attachment behaviour tested; bounce and complaint handling wired.

## Verification status

- Selected provider: yes (architectural decision).
- Verified connection: **no**. No account, credential or sandbox was used.
- Tested integration: **no**.
- Every item marked "not verified" in the matrix remains so until the provider confirms it in writing or the test passes.

## Architecture rules

- SIBVO owns the shared communication gateway: adapter contracts, country and capability-aware routing, organisation-specific provider configuration, connection health and verification, centralised secrets, verified webhook ingress (DFR1-012), the shared normalised envelope, the transactional outbox, delivery and call lifecycle audit, idempotency and retry policies, provider error normalisation, usage metering and cost attribution, and safe fallback and human handoff.
- Dealsflo consumes capabilities through stable provider-neutral contracts. No provider name appears in CRM or workflow business services.
- No duplicate registry, webhook engine, secrets store or outbox is introduced. Existing ones are extended.
- Each provider is an adapter with its own verifier, probe and capability declaration. Provider payloads and status values stay inside the adapter and are mapped to normalised values.
- Organisation-level enablement is explicit. A capability and a verified connection must both be enabled, and the server enforces it. The frontend cannot bypass this.

## Country and capability routing

- Routing is by country of the number, calling direction and capability. The router uses the configured primary provider for that combination. If it is not configured or not verified, the router refuses. It does not fall back to another provider unless the organisation has configured that fallback explicitly.
- India domestic: Exotel.
- International, supported countries: Twilio, per country and per direction. A direction that Twilio does not support for a country is refused and handed to a human.
- Unsupported country or direction: refused with a normalised reason. Nothing is placed.

## Consequences

- **DFR1-011** adds channel-specific connection verification and probes, one provider at a time, after this ADR is accepted and the DFR1-007 pull request is merged.
- **DFR1-027** (Exotel inbound lifecycle) starts only after the Exotel conditions are met and the DFR1-007 pull request is merged.
- **DFR1-012** verifier stays synthetic. Provider verifiers are added by their adapters.
- No provider adapter, probe or verifier is written by this decision.

## Alternatives considered and rejected

- Exotel for international calling: rejected as primary. Its India focus does not establish coverage for the target countries.
- Twilio for India: rejected as primary, because outbound calls to Indian numbers must originate from non-Indian numbers and toll-free numbers cannot be used outbound.
- Knowlarity: not selected. Its developer documentation was not verified.
- WhatsApp through a BSP at launch: not chosen. A BSP may be added later behind the same adapter contract.
