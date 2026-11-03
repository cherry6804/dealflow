# ADR-0032: Provider Registry and Connection Lifecycle

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decision Owners:** DealFlow Engineering
- **Jira:** DFR1-011 (shared registry and secrets boundary), prerequisite for DFR1-015 (AI gateway)

## Context

Dealsflo must use external providers (AI models, and later messaging, email and telephony) only when a verified, healthy connection exists (ADR-0029, Jira gate table). Before this ADR the codebase had encrypted credential storage (`provider_credentials`, ADR-0026 era and E06 WS1 to WS2) but no connection model: a credential was only a secret, a fixed list of provider keys was hardcoded, nothing verified a credential against a provider, and the execution policy denied every provider-dependent capability because no connection could exist.

The architecture document names `IntegrationProvider` and `IntegrationConnection` entities. The E01 provider matrix still lists the LLM provider as "Not selected". No real provider has been contacted, and CI has no provider credentials.

## Decision

1. **Code-owned provider registry.** Providers are defined in `backend/app/providers/registry.py` as immutable definitions: key, display name, category, declared operations, adapter status and an `executable` flag that is `False` for every provider today. The registry is the single source of provider keys for credentials and connections. Communication-channel providers (E04) register here too, so there is one registry.
   - **Deviation from the architecture entity list.** `IntegrationProvider` is not a database table. A provider's adapter, operations and status ship and are reviewed together in code. The registry stays extensible: adding a provider is a code change plus its adapter, and is covered by the same tests.
2. **OpenAI is the first LLM adapter (D1).** The adapter is in `openai_adapter.py`. Live access is controlled by `PROVIDER_LIVE_ADAPTERS_ENABLED`, which is **off by default** and is **never enabled in CI** (D6). With the flag off, verification reports `not_verified` and never contacts the network.
3. **A connection, not a credential, is what the product uses.** `provider_connections` references an existing encrypted credential in `provider_credentials` (AES-256-GCM, versioned, associated data bound to organization, provider and credential). The connection holds no secret. Credential storage is not duplicated (D4).
4. **Readiness is derived, not assumed.** `app/providers/readiness.py` decides readiness from the connection and the **current** credential. A provider is ready only when:
   - the connection status is `connected`;
   - its credential is active;
   - the credential version equals the version that passed verification;
   - the last successful verification is within `PROVIDER_CONNECTION_FRESHNESS_HOURS`.
   Rotation or revocation through any route, including the existing credential endpoints, makes the connection not ready without any write to the connection row.
5. **Lifecycle.** States are `unverified`, `verifying`, `connected`, `degraded`, `failed` and `disconnected`. Only a successful verification reaches `connected`. Transient failures move the connection to `degraded` with exponential backoff; reaching `PROVIDER_VERIFICATION_FAILURE_THRESHOLD` moves it to `failed`. Permanent rejection moves it to `failed` with no automatic retry. Rotation returns the connection to `verifying`. Disconnect revokes the credential, destroys its ciphertext and ends the connection.
6. **Verification runs in the worker (D5).** Creating, verifying and rotating a connection enqueue an outbox event (`provider.verification_requested`) in the same transaction. The WS3 worker runs the check under a row lock, so two checks for one connection run one after the other. Due re-verifications are queued by the worker's outbox loop, with idempotency keys that contain the due time. No provider call happens on an API request path.
7. **Verification history is kept (D7).** Each check writes a `provider_verification_attempts` row with outcome, reason code, latency, credential version and adapter version. Rows never contain a secret, a provider response body or a provider error message. History is returned only for the caller's organization.
8. **Permissions reuse the existing keys (D4).** Reads need `provider_credentials.read`. Every change needs `provider_credentials.manage`, which stays owner-only. No new permission keys were added.
9. **Honest status (D8).** Live provider verification is recorded as **Not verified** until a sandbox verification succeeds and its evidence is recorded. Until then the product shows "Not verified. Live provider access is disabled in this environment." Tests use a stub adapter defined in the test file only, and a mock HTTP transport for the real adapter's response mapping. No test presents a fake provider response as connectivity.
10. **Execution stays closed.** A ready provider does not enable any AI capability. The policy's provider gate now returns `provider_not_connected` when no provider is ready, as before, and `execution_gates_pending` when a provider is ready. The consent, budget, approval and resource-activation gates are not built, so the capability stays denied. SIBVO remains the authority for entitlements; the entitlement check still runs first and is unchanged.
11. **Audit.** Create, verification requested, rotate, disconnect and each verification outcome write an `AuditEvent` with the provider key, status, reason code and credential version. Worker-side events have no human actor.

## Alternatives Considered

- **Database-backed provider catalogue.** Rejected for now (D2). It would separate a provider's adapter from its definition and needs an admin workflow that is not yet approved. The registry can move to a table later if provider configuration must change without a release.
- **Store the connection state on the credential row.** Rejected. It would mix secret storage with product state and duplicate the single credential-management path.
- **Verify synchronously in the API request.** Rejected (D5). A provider call on the request path holds a connection open for the provider's latency and makes the API depend on provider availability.
- **Mark a connection connected when a key is saved.** Rejected. It is the "fake connected state" the requirements forbid.
- **A second credential-management system for connections.** Rejected. Credentials stay in `provider_credentials`.

## Consequences

- Operators must run the WS3 worker for verification and scheduled re-checks to happen. Until a worker is deployed (ADR-0026), connections stay `verifying`, and they are not usable. This is the correct fail-closed state.
- A connection can be ready while the AI capability is still denied. The UI must say both things. It does.
- Adding a provider requires a registry entry, an adapter, and tests for its response mapping. The stub adapter is not a product adapter.
- Owner-only controls are shown from the server's `can_manage` flag. The server still enforces the permission on every change.

## Security Considerations

- Secrets are accepted once on create and rotate, never returned, never logged, and never kept in frontend state after submission. A test scans attempt history, audit metadata, outbox payloads, the connection row and captured logs for the secret value.
- Every query is scoped to the caller's organization. Cross-organization identifiers return "not found", the same as the existing credential API.
- The verification job re-reads the connection and checks its organization before it touches the credential.
- A revoked credential is never sent to a provider.
- The live adapter sends the key only in the `Authorization` header to the configured provider base URL. Response bodies are not read into results.
- Provider data-use terms are not approved (E01 row 5). Enabling live access requires that approval first, so the flag is not a substitute for the decision.

## Operational Considerations

- Responsible operations team: DealFlow Engineering. No named individual owner, on-call rota or alert channel is configured.
- Operators can list attempts through the API. A reporting command is not built yet.
- Verification depends on the WS3 worker. The worker deployment prerequisites in `docs/development/worker-deployment.md` apply.
- **Required before live use:** an approved data-use and contract position for the provider, a sandbox account and recorded sandbox verification evidence, the production configuration for live access, and an approved decision to enable `PROVIDER_LIVE_ADAPTERS_ENABLED` in a named environment.

## Known Limitations

1. Live provider verification has **not** been performed. Its status is Not verified.
2. Live access is disabled by default and cannot be enabled in CI.
3. The registry is code-owned (see Decision 1). Adding a provider needs a release.
4. Frontend navigation has no menu entry for the page yet. It is reachable at `/settings/ai-providers`.
5. A verification that fails permanently, or that is dead-lettered by the worker, needs an operator replay (WS3) or a new verify request.
6. Scheduled re-verification depends on the worker process running. If it does not run, a connection stays at its last recorded state, and freshness expiry makes it not ready.
7. The attempt history has no retention purge (see WS3 D-7).

## Compatibility Considerations

- Additive migration `c3d8f1a9e2b7`: two tables. The downgrade drops them and does not change `provider_credentials`.
- Existing credential routes and their behavior are unchanged. `SUPPORTED_PROVIDER_KEYS` now comes from the registry and still contains only `openai`.
- The policy's provider gate keeps `provider_not_connected` for every case without a ready provider, so existing governance decisions are unchanged. A new reason code, `execution_gates_pending`, is added for a ready provider.

## Related Decisions

ADR-0026 (outbox and worker), ADR-0029 (AI execution and disabled-by-default policy), ADR-0031 (AI API namespace), ADR-0027 (SIBVO authority and entitlement snapshot), ADR-0028 (channel gateway, which reuses this registry).
