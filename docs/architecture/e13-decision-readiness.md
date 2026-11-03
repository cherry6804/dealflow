# E13 decision readiness: decision register, dependency and impact matrices, traceability and sequence

Status: **documentation only. No decision in this file is approved.** Every option is open. Every recommendation is a
recommendation for the named owner, not a decision. Where this file says "not built", it means the code does not exist
today, not that it is planned.

Sources: `docs/product/release-1/Dealsflo_Release1_Jira_Backlog_v2.xlsx` (acceptance criteria), `docs/adr/0026` to `0032`,
`docs/architecture/ai-governance-and-usage-controls.md`, `docs/architecture/sibvo-dealsflo-entitlement-contract.md`,
`docs/architecture/e13-completion-evidence.md` (sections 3, 6, 8, 11, 12, 13) and `docs/architecture/e13-decision-register.md`.

## Standing rules (apply to every decision)

- **SIBVO is the global authority** for identity, organizations, memberships, product membership, plans, subscriptions,
  trials, entitlements, seats and billing (contract section 1). Dealsflo never keeps a seat counter, grants subscription
  access, computes seat entitlements, or duplicates billing authority.
- **Dealsflo owns** its CRM records, its product roles and permissions, its team-membership rows, its usage events and its
  AI execution, workflows and product-level authorization.
- **Optional AI and automated communication stay disabled by default.** No option below enables them.
- **Authorization and tenant isolation are enforced server-side.** No option relies on the frontend.
- **Never invent** permission keys, entitlement keys, endpoints, schemas, retention periods or legal policies. Where a
  name below appears as an option, it is a placeholder for the owner to choose, not a key that exists.

## Mapping of decision IDs (read this first)

The user's labels for D1 and D9 differ from the labels in the existing register (`e13-decision-register.md` and
`e13-completion-evidence.md` section 3). Both sets are shown here so no one reads a decision under the wrong ID.

| ID used in this file | Title in this file | Label in the existing register |
|---|---|---|
| D1 | Data classification and ownership | D9: classification of remaining unclassified tables (section 5.8) |
| D9 | Export and deletion policy | D1: clear free-text fields on deletion (section 5.9), with export scope |
| D4 | Retention periods | D4: retention period per category |
| D7 | Worker scheduling and maintenance execution | D7: scheduler for maintenance jobs |
| D8 | Audit-event immutability and deletion handling | D8: audit immutability and deletion |
| D11 | Encryption at rest and key management | D11: encryption at rest for stored documents |
| D13 | Import attachment retention and privacy | D13: import source files |

Until the owner confirms the mapping, a decision reference in another document means the existing register's label.

---

## Part A: Decision register

Each decision lists the eleven required fields. "Current" facts were checked in code or docs on `origin/develop` at
`027d891`.

### Privacy and governance

#### D1. Data classification and ownership

1. **Current implementation and evidence.** `app/governance/table_inventory.py` records a disposition for every one of the
   69 tables. Those dispositions are enforced by `tests/test_table_inventory.py`. Section 5.8 of
   `ai-governance-and-usage-controls.md` proposes classifications for 27 tables that are "unclassified" by the proposal. The
   proposal is marked "for review, not authorization".
2. **Exact unresolved question.** Which owner classifies each tenant-owned table (personal data, financial record,
   operational, system), and who owns that classification for export and deletion purposes?
3. **Options.**
   - A. Approve section 5.8 as written.
   - B. Approve a modified classification, with changes listed per table.
   - C. Keep the current inventory dispositions and approve no new classification.
4. **Advantages and disadvantages.**
   - A: fastest; the proposal is already tabulated with personal data, export behaviour and foreign-key restrictions.
   - B: lets product correct rows the proposal gets wrong; needs a second review cycle.
   - C: no change; leaves 27 tables without an approved classification, so deletion and export of those tables cannot be
     approved.
5. **Security, privacy and tenant isolation.** Classification decides which tables are exported and deleted per
   organization. A wrong classification can leak another tenant's data into an export or delete a legal record. Each table
   query must stay scoped to `organization_id`.
6. **Impacted repositories and modules.** Dealsflo only. `app/governance/table_inventory.py`,
   `app/governance/data_classification.py`, `app/governance/privacy_execution.py`, `tests/test_table_inventory.py`. No
   migration is needed to record a classification in code; a new table would need one.
7. **Required tests and acceptance criteria.** Inventory test fails when any table lacks an approved disposition (already
   present). New test: every table classified as personal data is in the export inventory or has a recorded reason
   (not-covered notice). Acceptance: approval recorded in this file and the table inventory updated in one change.
8. **Dependencies and decision owner.** Depends on D9 (export and deletion policy) and D4 (retention). Owner: product and
   legal, per the existing register.
9. **Recommended option (recommendation, not an approved decision).** Option B. Review section 5.8 table by table, correct
   the rows that conflict with product behaviour, then approve. This is the least risky route to a complete classification.
10. **Consequences of delaying.** DFR1-050 deletion and export criteria for the 27 tables cannot close. The privacy
    controls cover only the tables already approved in the existing dispositions.

#### D4. Retention periods

1. **Current.** `RetentionPolicy` exists (`app/db/models/privacy_records.py`) with a retention mechanism. Only documents and
   invitations are enforced (`privacy_execution.py`). No period is set for any category, so none is enforced for the rest.
   Evidence section 3 records this as "no period is set".
2. **Exact unresolved question.** For each data category, what retention period applies, and what legal basis supports it?
3. **Options.**
   - A. Set a period per category, each with a legal basis recorded.
   - B. Set periods only for categories where a legal requirement exists, and keep everything else indefinite until review.
   - C. Keep the current state: only documents and invitations are retained, with no period for other categories.
4. **Advantages and disadvantages.**
   - A: complete; requires legal input for every category.
   - B: meets legal duties first; leaves some categories without any period, which is a retention gap that needs
     recording.
   - C: no legal input needed now; leaves DFR1-050's retention criterion Partial.
5. **Security, privacy and tenant isolation.** Retention runs delete data per organization. Each job must scope by
   `organization_id` and respect legal holds (`LegalHold`). A period set too short destroys records that law requires.
6. **Impacted repositories and modules.** Dealsflo: `RetentionPolicy` rows (configuration values, not a migration), the
   retention executor in `privacy_execution.py`, and the privacy maintenance job (`privacy_maintenance.py`). A new category
   needs an executor, which depends on D1 and D9.
7. **Required tests.** Per category with a period: retention job deletes only expired rows, skips rows under a legal hold,
   and writes the requested and completed audit records (existing pattern, tested for documents and invitations in
   `test_privacy_audit_independence.py`). Acceptance: each period is recorded with its legal basis.
8. **Dependencies and decision owner.** Depends on D1, D9 and D12 (legal holds, referenced in section 5.8). Owner: product and
   legal. No engineer may set a period.
9. **Recommended option (recommendation).** Option B: set periods for categories with a known legal requirement, record
   each one with its basis, and keep the rest unchanged until reviewed. Do not invent periods.
10. **Consequences of delaying.** DFR1-050 retention criterion stays Partial. Data without a period is kept indefinitely,
    which the privacy policy must acknowledge.

#### D7. Worker scheduling and maintenance execution

1. **Current.** Two maintenance jobs exist with `main()` entry points: `app/governance/privacy_maintenance.py:130` and
   `app/governance/usage_maintenance.py:61`. The outbox worker runs them only inside `_outbox_cycle` under
   `python -m app.outbox.worker --serve`. `--once` runs no sweep. Provider verification scheduling and stale detection run
   in the same cycle (`app/providers/health.py`, PR #149).
2. **Exact unresolved question.** Which process runs the maintenance jobs in each environment, at what interval, with what
   failure alerting, and who operates it?
3. **Options.**
   - A. Run the worker with `--serve` as a long-lived service, with health probes, and schedule the two jobs inside it.
   - B. Run `privacy_maintenance` and `usage_maintenance` as separate scheduled jobs (cron or the platform scheduler), each
     calling its `main()`.
   - C. Keep the current state: no deployed scheduler; the owner runs the jobs manually.
4. **Advantages and disadvantages.**
   - A: already implemented in code; one process to operate; a stuck cycle blocks outbox delivery too.
   - B: isolates maintenance from outbox delivery; needs a separate scheduler and monitoring.
   - C: no infrastructure; retention, reservation expiry and provider checks stop without anyone noticing.
5. **Security, privacy and tenant isolation.** Jobs run with the worker's database role, so they can cross tenants by design.
   Scheduling must not widen that role. Logs carry only error types, per PR #149.
6. **Impacted repositories and modules.** Dealsflo: `app/outbox/runtime.py`, `app/outbox/worker.py`, the two maintenance
   modules, and deployment configuration (not in this repository, see `docs/development/worker-deployment.md`).
7. **Required tests.** Existing: serve-cycle test in `test_provider_health.py`. Still needed: an end-to-end run of each
   maintenance `main()` against the test database, and a test that a failed job is logged and does not stop other work.
8. **Dependencies and decision owner.** Depends on the deployment environment and on D4 (retention periods must exist before
   a retention job has anything to enforce). Owner: infrastructure.
9. **Recommended option (recommendation).** Option A for the first environment (the code path is already tested), with
   health probes and alerting on the worker. Revisit B if maintenance load grows.
10. **Consequences of delaying.** Reservation expiry and stale provider detection run only where someone started the worker.
    Usage budgets can hold reservations open. DFR1-017 maintenance and DFR1-050 retention stay Partial.

#### D8. Audit-event immutability and deletion handling

1. **Current.** Migration `b4d8f2a6c1e9` adds the trigger `audit_events_immutable`, which rejects `UPDATE`. It allows the
   `ON DELETE SET NULL` foreign-key action. No trigger blocks `DELETE`. Test fixtures delete audit rows directly
   (`_cleanup` in several test files).
2. **Exact unresolved question.** Should audit rows be deletable at all, and if so, under which controlled path (retention,
   tenant deletion, legal request), by which role, and with what record of the deletion?
3. **Options.**
   - A. Block `DELETE` with a trigger, and provide no deletion path. Tests clean up through a privileged test-only path.
   - B. Block `DELETE` with a trigger, and provide one controlled retention path that writes a deletion record first.
   - C. Keep the current state: `UPDATE` blocked, `DELETE` allowed.
4. **Advantages and disadvantages.**
   - A: strongest evidence guarantee; needs a test-only bypass, which must be kept out of production paths.
   - B: supports retention and legal erasure; more design work, and a deletion record must itself be immutable.
   - C: no work; any database role can erase evidence, so audit is not independent evidence.
5. **Security, privacy and tenant isolation.** Audit rows contain actor and resource identifiers. Deleting them can break
   the traceability that privacy and billing decisions rely on. A deletion path that a tenant can trigger would destroy
   evidence of that tenant's own actions. Any bypass must be role-restricted and must not be reachable through the API.
6. **Impacted repositories and modules.** Dealsflo: a new migration would add a `BEFORE DELETE` trigger and any deletion
   function. `app/audit/independent.py`, the `ON DELETE SET NULL` foreign keys on `audit_events`, and test cleanup
   helpers in about a dozen test files.
7. **Required tests.** Option A: `DELETE` on `audit_events` raises; user and organization deletion still succeeds through
   `SET NULL`; the test-only bypass is unavailable outside the test environment. Option B: the controlled path writes a
   deletion record that itself cannot be deleted; a tenant cannot reach the path.
8. **Dependencies and decision owner.** Depends on D4 and D12 (legal holds). Owner: security and legal.
9. **Recommended option (recommendation).** Option B, delivered as two steps: first block `DELETE` with a trigger that
   allows only the `SET NULL` action, with the test bypass gated on the test environment; then design the controlled path
   after D4 sets retention periods. Do not ship the trigger until the test cleanup path is updated, because it breaks
   fixtures.
10. **Consequences of delaying.** Audit rows can be deleted directly by any role with `DELETE`. That undermines the audit
    criterion in DFR1-050. The prior design attempt in this unit found the trigger would break the foreign-key action,
    so the change needs a planned migration, not an opportunistic one.

#### D9. Export and deletion policy

1. **Current.** Export covers customer profiles, requirements, deals, AI and CRM sub-records, with "not covered" notices
   (`privacy_execution.py`, PR #148 and earlier). Deletion covers documents, invitations and contacts with deferral when
   live records depend on them. Free-text fields are inventoried in section 5.9 of `ai-governance-and-usage-controls.md`.
   Nothing is cleared: categories without an approved executor report `deletion_executor_not_built`.
2. **Exact unresolved question.** Which personal free-text fields may be cleared on deletion (option set from section 5.9),
   and which records are deleted rather than cleared? Which categories must be included in export?
3. **Options.**
   - A. Approve the free-text clearing scope in section 5.9 as written, plus its deletion rule.
   - B. Approve a narrower scope, clearing only fields a named legal requirement needs cleared.
   - C. Keep the current policy: no clearing, deletion only for categories with an executor, export as now.
4. **Advantages and disadvantages.**
   - A: completes the deletion criterion for those fields; irreversible, so it needs legal sign-off.
   - B: lower risk; leaves some personal content in place.
   - C: no destructive change; deletion requests for those categories stay incomplete and must be reported as such.
5. **Security, privacy and tenant isolation.** Clearing is destructive. It must run per organization, respect legal holds,
   and not clear financial or legal records (section 5.9 marks them). The clearing job must be audited (requested and
   completed records, as for documents).
6. **Impacted repositories and modules.** Dealsflo: `privacy_execution.py` (executor per category), `data_classification.py`,
   `table_inventory.py`, the contact and deal models that hold the free-text fields.
7. **Required tests.** Per approved field: cleared on deletion, not cleared when a legal hold applies, financial record
   untouched, audit requested and completed records written, cross-organization rows untouched.
8. **Dependencies and decision owner.** Depends on D1 (classification) and D4 (retention). Owner: product and legal.
9. **Recommended option (recommendation).** Option B. Approve only the fields that a legal requirement needs cleared, and
   leave the rest for a second review. Clearing is one-way, so start narrow.
10. **Consequences of delaying.** DFR1-050 deletion criterion stays Partial. Deletion requests report
    `deletion_executor_not_built` for those categories, which must be disclosed to the data subject.

#### D11. Encryption at rest and key management

1. **Current.** Provider credentials are encrypted with AES-256-GCM and a keyring (`app/provider_secrets/cipher.py`,
   `key_provider.py`), with the keyring supplied by configuration (`PROVIDER_SECRETS_KEYRING`). Stored documents use private
   local storage without encryption at rest (evidence section 3). The backlog criteria for DFR1-050 do not mention
   encryption; it is an open decision from the evidence document, not an acceptance criterion.
2. **Exact unresolved question.** Should stored documents and privacy artifacts be encrypted at rest, and if so, under which
   managed key service, with which rotation, and with what key-custody owner?
3. **Options.**
   - A. Use the platform's managed key service for envelope encryption of documents, with rotation and audited key use.
   - B. Extend the existing keyring mechanism to documents, with keys supplied by configuration.
   - C. Keep the current state: private local storage, no encryption at rest.
4. **Advantages and disadvantages.**
   - A: strongest custody; depends on a service that must be selected and approved.
   - B: no new service; keys live in configuration, so custody depends on the deployment's secret handling.
   - C: no work; document content is readable by anyone with storage access.
5. **Security, privacy and tenant isolation.** Encrypting per organization (separate data keys per tenant) limits the impact
   of a key compromise to one tenant. Keys must never be logged, returned in responses or stored with the ciphertext.
6. **Impacted repositories and modules.** Dealsflo: the document service (`app/documents/service.py`), the storage path,
   `provider_secrets` (as the reference pattern), configuration (`app/config.py`), and a migration to store key identifiers
   with each stored object. Existing objects need a re-encryption job.
7. **Required tests.** Round trip for each stored object type; tampered ciphertext rejected; key rotation re-encrypts;
   plaintext never written to storage; a wrong-tenant key cannot decrypt another organization's object.
8. **Dependencies and decision owner.** Infrastructure and security. Depends on the managed-key service decision.
9. **Recommended option (recommendation).** Option B now, with per-organization data keys wrapped by a key from the platform
   key service once that service is chosen. Option B reuses a tested pattern and is independent of the managed-key choice.
10. **Consequences of delaying.** Documents and privacy artifacts stay unencrypted at rest. This is disclosed as a known
    limitation, not claimed as met.

#### D13. Import attachment retention and privacy

1. **Current.** Import source files are stored with their batch. Evidence section 3 records them as "not exported and not
   deleted" by the privacy path. The existing register proposes treating them as organization-owned documents, removed with
   their batch after retention.
2. **Exact unresolved question.** How long are import source files kept, who owns them, and do they fall under the
   document-retention rules or a separate rule?
3. **Options.**
   - A. Treat import source files as documents: same retention, export and deletion as documents.
   - B. Keep them with their batch, and delete them when the batch is deleted, with no separate retention period.
   - C. Keep the current state: not exported, not deleted.
4. **Advantages and disadvantages.**
   - A: consistent with documents; needs D4 periods for documents first.
   - B: simple; batch deletion can happen before a legal hold is checked.
   - C: no work; personal data in import files is kept indefinitely and is missing from export.
5. **Security, privacy and tenant isolation.** Import files often contain personal data of people who are not customers. They
   must be scoped to the organization and must not appear in another tenant's export.
6. **Impacted repositories and modules.** Dealsflo: `app/imports/service.py`, `app/imports/processing_service.py`, the
   document service, and `privacy_execution.py`.
7. **Required tests.** Export includes import source files for the requesting organization only; deletion respects legal
   holds; batch deletion writes the requested and completed audit records.
8. **Dependencies and decision owner.** Depends on D4 and D9. Owner: product.
9. **Recommended option (recommendation).** Option A, because it reuses the document rules once D4 sets them.
10. **Consequences of delaying.** Import source files stay outside export and retention. This is a gap for any data-subject
    request that covers imported records.

### Authorization and entitlements

#### AI actor permission key

1. **Current.** The execution gate's actor check uses `DEFAULT_AI_PERMISSION = "ai.execute"`
   (`app/governance/execution_gate.py`). `ai.execute` is not in the permission catalogue (`app/authz/permissions.py`), so no
   role can hold it and every AI execution is refused at the actor gate. Tests change the key through
   `tests/governance_helpers.py`. Owners receive every catalogued key, so they are also refused.
2. **Exact unresolved question.** Which permission key lets a member initiate AI execution, and which roles hold it? Is there
   one key for all AI capabilities, or one per capability?
3. **Options.**
   - A. One catalogued key (name chosen by the owner), granted to the roles the product matrix names.
   - B. One key per capability category (AI, automation, communication), each catalogued.
   - C. Keep the current state: no key; AI execution is refused for everyone.
4. **Advantages and disadvantages.**
   - A: smallest change; coarse, so a member who may use one AI feature may use all.
   - B: finer control; more keys to maintain and to explain to customers.
   - C: safe, but no AI capability can ever execute, which blocks DFR1-006 and DFR1-015 from reaching the executor.
5. **Security, privacy and tenant isolation.** The key is checked per organization against that organization's roles, so
   it must stay in the server-side catalogue. A key granted in one organization must never apply in another.
6. **Impacted repositories and modules.** Dealsflo: `app/authz/permissions.py`, `app/governance/execution_gate.py`,
   `app/governance/policy.py`, role provisioning (`provision_default_organization_roles`), and the frontend role matrix if
   it lists keys.
7. **Required tests.** Catalogue test that the key exists; a member without it is refused; a member with it passes the actor
   gate only; owner-only behaviour if the key is owner-only; cross-organization denial.
8. **Dependencies and decision owner.** Product (role matrix) and security. Depends on the role-granting decision below.
9. **Recommended option (recommendation).** Option A, with one new catalogued key, granted to no role by default and
   assigned explicitly by the owner. This is a recommendation; the name and the role grants are for the owner to choose.
10. **Consequences of delaying.** AI execution cannot be enabled for any organization. DFR1-006 "no executor exists" stays
    true, and DFR1-015 cannot be verified end to end.

#### AI capability entitlement keys

1. **Current.** Every AI capability uses one SIBVO entitlement, `ai_gateway` (`app/governance/capabilities.py`), which is
   Boolean with no limit (contract section 2.4). Each AI capability in the catalogue has `requires_provider=True` and
   `entitlement_feature=AI_GATEWAY_ENTITLEMENT`. The contract's feature-limit table lists only `workflow_automation`
   in the SIBVO catalogue (section 6).
2. **Exact unresolved question.** Should AI capabilities keep one entitlement (`ai_gateway`), or should SIBVO define one key
   per capability? Which key is the source for each Dealsflo capability? Confirm the names with SIBVO's catalogue.
3. **Options.**
   - A. Keep `ai_gateway` for all AI capabilities.
   - B. Define one SIBVO key per AI capability (names set by SIBVO), each mapped in the catalogue.
   - C. Keep `ai_gateway` now and add per-capability keys later, without changing the mapping of existing capabilities.
4. **Advantages and disadvantages.**
   - A: already implemented and snapshot-tested; coarse (all AI on or off per plan).
   - B: finer plan control; needs a SIBVO catalogue change and a migration of the mapping.
   - C: no immediate change; a later mapping change must be tested for existing grants.
5. **Security, privacy and tenant isolation.** Entitlement is the plan's grant, not a user's. The snapshot is signed and
   organization-bound (`test_org_entitlement_snapshot.py`). A new key must be checked for each capability, and a missing key
   must deny (see fail-closed decision).
6. **Impacted repositories and modules.** SIBVO: the entitlement catalogue and its snapshot. Dealsflo: `capabilities.py`,
   `policy.py`, `integrations/org_entitlement_snapshot.py`, and the golden-vector test shared with SIBVO.
7. **Required tests.** Per capability: granted when its key is enabled, denied when disabled, denied when missing
   (`entitlement_not_defined`); golden vector still passes; the snapshot carries every key.
8. **Dependencies and decision owner.** SIBVO product owner (DFR1-005). Blocks any per-capability plan control.
9. **Recommended option (recommendation).** Option C: keep `ai_gateway`, ask SIBVO to confirm whether plan-level control per
   capability is required before adding keys.
10. **Consequences of delaying.** DFR1-005 stays open, so DFR1-006 entitlement criteria stay Partial, and AI cannot be
    sold per capability.

#### Channel execution permission and entitlement keys

1. **Current.** Channel sending is fail-closed. Evidence section 6.2: "keep channel sending fail-closed. Do not grant a send
   permission to any role." Channel policy permissions exist for configuration only
   (`governance.channels.read` and `governance.channels.manage`). No channel send permission or channel entitlement key
   exists.
2. **Exact unresolved question.** Which permission key authorizes a member to send through a channel, which roles hold it,
   and which SIBVO entitlement (if any) gates channels?
3. **Options.**
   - A. A catalogued send key (for example, one per channel or one for all channels), granted to the roles the matrix names.
   - B. Reuse `governance.channels.manage` for sending. Simpler, but configuration rights would then imply sending rights.
   - C. Keep fail-closed: no send permission and no channel entitlement.
4. **Advantages and disadvantages.**
   - A: separates configuration from sending; a new key to explain.
   - B: no new key; mixes two duties, which is a segregation-of-duties risk.
   - C: safe; no channel can send, so the communication epics cannot be verified.
5. **Security, privacy and tenant isolation.** Sending reaches a third party and a contact. Consent (DND, quiet hours, channel
   policy) is checked in the gate. Sending must be audited with the initiating user, and never from a frontend-only check.
6. **Impacted repositories and modules.** Dealsflo: `app/authz/permissions.py`, `channel_policy.py`,
   `execution_gate.py`, and the channel gateway when it exists (ADR-0028, Proposed).
7. **Required tests.** Existing: `test_channel_send_authorization.py`. Add: a send key granted to a role passes the actor gate
   only when consent and channel policy also pass; a configuration-only role is refused; owner behaviour matches the key's
   owner-only status.
8. **Dependencies and decision owner.** Product and security. Depends on ADR-0028 being accepted, and on the entitlement
   decision above.
9. **Recommended option (recommendation).** Option A, with its own key, and do not reuse `governance.channels.manage`. Keep
   the key ungranted until ADR-0028 is accepted.
10. **Consequences of delaying.** Channel sending stays impossible. Communication epics (E03, E04) cannot be verified.

#### Role-granting and administrative authority

1. **Current.** Owner-only keys are defined (`OWNER_ONLY_PERMISSION_KEYS` in `permissions.py`) and the owner role holds every
   catalogued key. Owner-only keys include `governance.capabilities.manage`, `governance.budgets.manage`,
   `governance.privacy.manage`, `governance.consent.manage`, `governance.approvals.decide`,
   `governance.channels.manage` and `provider_credentials.manage`. Role assignment is handled by the team module
   (`app/team/`). Tests: `test_owner_only_authorization.py`.
2. **Exact unresolved question.** Which roles other than owner may hold the administrative keys, and who may assign roles
   (only owners, or also administrators)?
3. **Options.**
   - A. Keep owner-only for every administrative key.
   - B. Allow a named administrative role to hold selected keys, assigned only by owners.
   - C. Allow role assignment by any administrator, with an audit trail.
4. **Advantages and disadvantages.**
   - A: strongest; slows routine administration.
   - B: practical; needs a new role and its tests.
   - C: convenient; widens privilege escalation risk.
5. **Security, privacy and tenant isolation.** Role changes must be checked against the actor's own role in the same
   organization. Self-escalation must be refused. SIBVO owns memberships and product membership, so Dealsflo role grants
   remain product-level only.
6. **Impacted repositories and modules.** Dealsflo: `app/authz/`, `app/team/`, role provisioning, and the frontend role UI.
7. **Required tests.** Owner-only keys refused for non-owners (existing); a non-owner cannot grant a role to themselves; cross-
   organization role assignment refused; audit record written for every grant.
8. **Dependencies and decision owner.** Product and security.
9. **Recommended option (recommendation).** Option A for now. Revisit B when customers need delegated administration.
10. **Consequences of delaying.** Current owner-only behaviour remains. Customers with many administrators must share the
    owner role, which is a usability gap, not a security gap.

#### Fail-closed behaviour when entitlements are unavailable

1. **Current.** Snapshot unavailability denies: an unreachable SIBVO with no valid stored snapshot denies
   (`test_missing_snapshot_with_sibvo_unreachable_is_denied`). An expired snapshot is never used
   (`test_an_expired_snapshot_is_never_used_and_outage_denies`). A missing feature key returns `entitlement_not_defined`
   (`policy.py`). A downgrade due while SIBVO is unreachable does not extend the old grant (WP-E13-next). The signed
   snapshot is 30 seconds, so the bound is 30 seconds plus the revalidation interval.
2. **Exact unresolved question.** Is the current fail-closed behaviour the approved policy for every entitlement, including
   revalidation interval and backoff limits? Is any grace period permitted, and for which features?
3. **Options.**
   - A. Keep current behaviour: deny whenever no valid unexpired snapshot exists. No grace period.
   - B. Allow a grace period for a named feature, stated in seconds, with an audit record when it is used.
   - C. Serve the last snapshot indefinitely during an outage.
4. **Advantages and disadvantages.**
   - A: safe; a SIBVO outage stops AI for everyone until SIBVO answers.
   - B: keeps service during short outages; a revoked entitlement can remain usable for the grace period.
   - C: no service impact; revocation is never enforced during an outage, which the contract forbids.
5. **Security, privacy and tenant isolation.** The bound on how long a revoked grant survives is the security property. Any
   grace period widens that bound and must be per organization.
6. **Impacted repositories and modules.** Dealsflo: `org_entitlement.py`, `org_entitlement_snapshot.py`, `policy.py`,
   the revalidation interval setting.
7. **Required tests.** Existing: the outage and expiry tests above. Add for any grace period: granted within it and recorded;
   denied after it; revocation during the period still denied at the next revalidation.
8. **Dependencies and decision owner.** Product and security. Depends on the entitlement decisions.
9. **Recommended option (recommendation).** Option A. The current implementation already follows it and it matches the
   contract. Do not add a grace period without a stated business need.
10. **Consequences of delaying.** None; current behaviour is safe and tested. Delay only leaves the policy undocumented as
    approved.

### SIBVO integration

#### Usage-ingestion contract

1. **Current.** Blocked. SIBVO has no usage-ingestion endpoint. Dealsflo has no usage client and no usage-event producer. The
   contract section 7 is marked "Proposed, for approval". Dealsflo's usage ledger (`usage_ledger.py`) is local and not
   reported to SIBVO.
2. **Exact unresolved question.** Does SIBVO accept usage events from Dealsflo, and if so, at which endpoint, with which
   authentication, schema, rate limits and failure responses?
3. **Options.**
   - A. Approve the proposed contract in section 7 of the contract document as written.
   - B. Approve a modified contract after SIBVO's billing owner reviews the meters.
   - C. Keep usage local to Dealsflo. SIBVO billing does not see AI usage; enterprise AI billing is handled outside the platform.
4. **Advantages and disadvantages.**
   - A: fastest; SIBVO must build the endpoint and reconciliation.
   - B: lets SIBVO's meters shape the contract; more review.
   - C: no integration; AI usage cannot be billed or reconciled through SIBVO.
5. **Security, privacy and tenant isolation.** The event must carry `organization_id` and `product_key` and must be authenticated
   as a service call (the same confidential client pattern as section 2.4). A forged event must not credit another tenant.
6. **Impacted repositories and modules.** SIBVO: a new ingestion endpoint, meters, reconciliation. Dealsflo: a usage client
   (the only SIBVO client is `app/integrations/sibvo_client.py`), an outbox event type, and the usage ledger as the source.
7. **Required tests.** Dealsflo: outbox delivery with a fake SIBVO; duplicate delivery produces one SIBVO record; a forged
   event is rejected. SIBVO: its own contract tests (not in this repository).
8. **Dependencies and decision owner.** SIBVO platform owner and billing owner (DFR1-053). Depends on DFR1-017 (Dealsflo usage
   producer) and DFR1-036.
9. **Recommended option (recommendation).** Option B. Split DFR1-053 into 053a (Dealsflo producer and outbox, after DFR1-017)
   and 053b (SIBVO ingestion, after DFR1-036), as recorded in contract section 7.1.
10. **Consequences of delaying.** DFR1-053 usage summaries and reconciled usage stay Blocked. AI usage is not billed through
    SIBVO.

#### Event schema and versioning

1. **Current.** The proposed event (contract section 7) has `event_id`, `organization_id`, `product_key`, optional `user_id`,
   `feature_key`, `quantity`, and `occurred_at`. No version field is defined. Session and snapshot payloads already carry
   `version: 1` (section 2.4), a precedent.
2. **Exact unresolved question.** Does the event carry an explicit schema version, and how is a breaking change negotiated?
3. **Options.**
   - A. Add an integer `schema_version` to every event; SIBVO rejects unknown versions.
   - B. Use the snapshot's `version` convention and keep one version until a breaking change.
   - C. No version field; changes are additive only, enforced by review.
4. **Advantages and disadvantages.**
   - A: explicit; needs SIBVO to support multiple versions during a change.
   - B: consistent with the existing snapshot; coarser.
   - C: simplest; a breaking change is not detectable by the receiver.
5. **Security, privacy and tenant isolation.** Version checks must happen before any tenant credit is applied, so an
   unknown version cannot be used to bypass validation.
6. **Impacted repositories and modules.** SIBVO ingestion; Dealsflo event producer.
7. **Required tests.** Unknown version rejected; known version accepted; additive field tolerated; contract golden vector
   for the event.
8. **Dependencies and decision owner.** SIBVO platform owner, with Dealsflo.
9. **Recommended option (recommendation).** Option B, to match the existing snapshot convention, with a documented rule for
   breaking changes.
10. **Consequences of delaying.** The producer cannot be written without a shape to target. Blocks the producer half of
    DFR1-053a.

#### Idempotency and deduplication

1. **Current.** Dealsflo: `usage_ledger.py` enforces idempotency on `(organization_id, idempotency_key)` with a request
   fingerprint, and a repeat with the same payload returns the stored entry (PR #148 tests). SIBVO: the proposal stores
   `(organization_id, product_key, event_id)` and returns the existing result for a repeat. Not built.
2. **Exact unresolved question.** Is the dedup key `event_id` alone, or `(organization_id, product_key, event_id)` as
   proposed, and what does SIBVO return on a repeat with a different payload?
3. **Options.**
   - A. As proposed: key `(organization_id, product_key, event_id)`; a repeat with a different payload is refused.
   - B. As A, plus a payload hash stored with the key, so a conflicting repeat is audited.
   - C. `event_id` globally unique; a repeat from another organization is refused.
4. **Advantages and disadvantages.**
   - A: matches the contract; a conflicting repeat is refused but not necessarily audited.
   - B: adds evidence of tampering; a little more storage.
   - C: prevents cross-tenant reuse of an id; relies on id generation quality.
5. **Security, privacy and tenant isolation.** The key must include the organization, so one tenant cannot block another's
   events by reusing an id. Option C also protects against that, but relies on the client's id generation.
6. **Impacted repositories and modules.** SIBVO ingestion table and its unique constraint; Dealsflo ledger (already enforced).
7. **Required tests.** Repeat returns the same result; conflicting repeat refused and audited (option B); two organizations
   using the same `event_id` both succeed under option A.
8. **Dependencies and decision owner.** SIBVO platform owner.
9. **Recommended option (recommendation).** Option B: the contract's key plus a stored payload hash, so a conflicting repeat
   is detectable.
10. **Consequences of delaying.** Duplicate or conflicting usage could be double-counted once SIBVO ingests events.

#### Usage reversal and correction

1. **Current.** Dealsflo reverses a usage entry with an audit trail (`reverse` in `usage_ledger.py`, PR #148). SIBVO has no
   reversal or correction event in its proposal. A reversal in Dealsflo does not reach SIBVO.
2. **Exact unresolved question.** Is a reversal sent to SIBVO as a negative quantity, as a separate event type referencing the
   original `event_id`, or not sent at all (local correction only)?
3. **Options.**
   - A. Separate reversal event referencing the original `event_id`; SIBVO nets it against the original.
   - B. Negative-quantity event with a new `event_id`.
   - C. No reversal sent; SIBVO reconciles from its own records and the difference is reviewed manually.
4. **Advantages and disadvantages.**
   - A: explicit and auditable; needs a reference rule.
   - B: simple; loses the link to the original.
   - C: no integration work; corrections are invisible to billing until reviewed.
5. **Security, privacy and tenant isolation.** A reversal must reference an event of the same organization and product;
   a reversal must not reverse another tenant's event.
6. **Impacted repositories and modules.** SIBVO ingestion and reconciliation; Dealsflo ledger reversal (existing) and the
   outbox producer.
7. **Required tests.** Reversal references an existing own event; reversal of another organization's event refused;
   reversal applied once; net usage after reversal equals the expected value.
8. **Dependencies and decision owner.** SIBVO billing owner, with Dealsflo.
9. **Recommended option (recommendation).** Option A, because it keeps the audit link.
10. **Consequences of delaying.** Corrections stay local, so billed usage can differ from the ledger until manual review.

#### Retry, replay and reconciliation

1. **Current.** The contract proposes at-least-once delivery from the Dealsflo outbox with bounded backoff (ADR-0026), and
   SIBVO reconciliation that compares accepted events with its meters. Dealsflo's outbox exists and is tested
   (`test_outbox.py`). SIBVO reconciliation is not built. A replay tool exists for outbox events (`app/outbox/replay.py`), but
   it is not a billing replay.
2. **Exact unresolved question.** What is the retry limit and backoff for usage delivery, who may replay a dead-lettered event,
   how often does SIBVO reconcile, and what happens to a mismatch?
3. **Options.**
   - A. Outbox retry with a fixed attempt limit, then dead-letter; operator replay through the existing tool; daily SIBVO reconciliation that opens a review item for each mismatch.
   - B. As A, with automatic re-delivery of dead-lettered events after an operator confirms the cause.
   - C. Manual reconciliation only, no automatic retries.
4. **Advantages and disadvantages.**
   - A: uses existing machinery; operators must act on dead letters.
   - B: fewer manual steps; risk of re-sending events that failed for a reason that is not transient.
   - C: no automation; mismatches found late.
5. **Security, privacy and tenant isolation.** Replay must keep the original `organization_id`; an operator replay must be audited
   with the operator's identity.
6. **Impacted repositories and modules.** Dealsflo: `app/outbox/service.py`, `app/outbox/replay.py`, `outbox_replay_record.py`.
   SIBVO: reconciliation job.
7. **Required tests.** Attempt limit reached dead-letters the event; replay re-delivers once and is audited; reconciliation
   reports a seeded mismatch and does not change billing.
8. **Dependencies and decision owner.** Platform operations and SIBVO billing owner.
9. **Recommended option (recommendation).** Option A.
10. **Consequences of delaying.** Failed usage delivery has no defined recovery; events may be lost or double-counted.

#### Product identity and organization mapping

1. **Current.** The contract identifies Dealsflo by `product_key`, configured as `sso_dealsflo_product_key` (`dealsflo`)
   in SIBVO and `SIBVO_ORG_SNAPSHOT_SIGNING_KEY` in Dealsflo. Snapshots carry `organization_id` and `product_key`, and a snapshot for
   another organization is rejected (`test_a_snapshot_for_another_organization_is_rejected`). Dealsflo's organization id is
   SIBVO's organization id in the snapshot path; the mapping is not described in a separate table.
2. **Exact unresolved question.** Is the Dealsflo organization id always the SIBVO organization id (the current assumption),
   or is there a separate mapping, and who owns the mapping when an organization is created or merged?
3. **Options.**
   - A. Keep one id: the SIBVO organization id is the Dealsflo organization id for every product.
   - B. Keep a product-level mapping table owned by Dealsflo, populated from SIBVO identifiers.
   - C. Mapping owned by SIBVO and exposed through the snapshot.
4. **Advantages and disadvantages.**
   - A: simplest; already in use.
   - B: lets Dealsflo rename or split internally; a second source of truth to keep consistent, which the rules forbid for
     membership.
   - C: keeps SIBVO authoritative; needs a SIBVO field.
5. **Security, privacy and tenant isolation.** Any mapping must be unique per organization and product, and a lookup must
   never return another tenant's record. Option B introduces a table that could drift from SIBVO.
6. **Impacted repositories and modules.** Dealsflo: `sibvo_client.py`, the organization model, snapshot verification. SIBVO:
   organization identifiers.
7. **Required tests.** Existing snapshot tests cover organization binding. Add for any mapping: unmapped organization denied;
   two products mapped to one organization do not share rows.
8. **Dependencies and decision owner.** SIBVO platform owner.
9. **Recommended option (recommendation).** Option A. It matches the rule that SIBVO is the authority for organizations.
10. **Consequences of delaying.** None while Option A holds. A future multi-product change needs this decided first.

#### Ownership of billing webhook ingestion

1. **Current.** SIBVO owns billing (contract section 1). Dealsflo has `BillingWebhookEvent` and `BillingReconciliationRecord`
   models, and a reconciliation service that consumes stored events (`app/billing/reconciliation_service.py`). No Dealsflo code
   inserts `BillingWebhookEvent` rows, and no Dealsflo endpoint receives or replays a billing webhook. The reconciliation
   records are readable through `/api/v1/billing/audit/reconciliations`.
2. **Exact unresolved question.** Which system receives the provider's billing webhook, and does Dealsflo ever receive
   billing events, or only SIBVO's derived entitlement changes?
3. **Options.**
   - A. SIBVO receives the webhook; Dealsflo receives only the derived entitlement snapshot. Remove Dealsflo's billing
     reconciliation models or keep them as unused legacy.
   - B. SIBVO receives the webhook and forwards billing events to Dealsflo as signed events.
   - C. Dealsflo receives the webhook directly, as the models suggest.
4. **Advantages and disadvantages.**
   - A: matches the authority rule; leaves dead models to clean up.
   - B: lets Dealsflo audit billing events; adds a second receiver contract and more duplication of billing data.
   - C: conflicts with the rule that Dealsflo never duplicates billing authority; a second billing source.
5. **Security, privacy and tenant isolation.** Option C would hold billing payloads, which contain payment data, in a second
   system. Option B needs signing and replay protection.
6. **Impacted repositories and modules.** SIBVO repository billing module (`app/modules/billing/`, not in this repository). Dealsflo: `app/billing/`,
   `app/api/billing_audit.py`, `BillingWebhookEvent`, `BillingReconciliationRecord`.
7. **Required tests.** Option A: no Dealsflo code path stores billing payloads; the snapshot path is the only billing input.
   Option B: signed forwarded event verified; replay of the same event produces one record (existing service test pattern).
8. **Dependencies and decision owner.** SIBVO platform owner and product owner.
9. **Recommended option (recommendation).** Option A. Confirm the models are legacy, then decide whether to remove them in a
   separate change.
10. **Consequences of delaying.** The "replay through the endpoint" objective stays unmeetable. The reconciliation endpoints
    stay readable but receive no data.

#### Failure handling and auditability

1. **Current.** Dealsflo audits governed changes with requested and completed records (WP3, PR #142 and later). Usage
   reversals and budget changes are audited (PR #148). The SIBVO snapshot path records outcomes in its own tests but
   emits no product-level audit row for a downgrade or outage. Failures are logged with error types only.
2. **Exact unresolved question.** Which SIBVO-side failures must produce a Dealsflo audit record (outage, rejected
   signature, denial, downgrade), and which may be logged only?
3. **Options.**
   - A. Audit every denial caused by a rejected or expired snapshot; log outages only.
   - B. Audit every snapshot decision that changes access (grant to deny, deny to grant), plus outages.
   - C. Log only; no audit for SIBVO-side failures.
4. **Advantages and disadvantages.**
   - A: traceable denials; high volume during an outage.
   - B: records every access change; needs de-duplication, like the stale-episode key in PR #149.
   - C: no volume; no evidence of why a feature stopped.
5. **Security, privacy and tenant isolation.** Audit rows must not contain signatures, keys or SIBVO response bodies. They must
   be per organization.
6. **Impacted repositories and modules.** Dealsflo: `org_entitlement.py`, `org_entitlement_snapshot.py`, the audit module.
7. **Required tests.** Option B: access change writes one episode record (idempotent key pattern from PR #149); no secret in
   metadata; outage logged without a response body.
8. **Dependencies and decision owner.** Security and product.
9. **Recommended option (recommendation).** Option B, with the episode key pattern already used for provider staleness.
10. **Consequences of delaying.** An entitlement-driven denial cannot be explained afterwards.

---

## Part B: Decision dependency matrix

Read across: a decision in a row depends on the decisions marked "X" in its columns.

| Decision | D1 | D4 | D7 | D8 | D9 | D11 | D13 | AI actor key | AI entitlement keys | Channel keys | Role grants | Fail-closed | Usage contract | Event schema | Idempotency | Reversal | Retry/replay | Identity mapping | Webhook ownership | Failure audit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 | - | | | | | | | | | | | | | | | | | | | |
| D4 | X | - | | | | | | | | | | | | | | | | | | |
| D7 | | X | - | | | | | | | | | | | | | | | | | |
| D8 | | X | | - | | | | | | | | | | | | | | | X | |
| D9 | X | X | | | - | | | | | | | | | | | | | | | |
| D11 | | | | | | - | | | | | | | | | | | | | | |
| D13 | | X | | | X | | - | | | | | | | | | | | | | |
| AI actor key | | | | | | | | - | | | X | | | | | | | | |
| AI entitlement keys | | | | | | | | | - | | | X | X | | | | | X | |
| Channel keys | | | | | | | | | | - | X | | | | | | | | |
| Role grants | | | | | | | | | | | - | | | | | | | | |
| Fail-closed | | | | | | | | | | | | - | | | | | | | |
| Usage contract | | | | | | | | | | | | | - | X | X | X | X | X | X | |
| Event schema | | | | | | | | | | | | | | - | | | | | |
| Idempotency | | | | | | | | | | | | | | X | - | | | | |
| Reversal | | | | | | | | | | | | | | X | X | - | | | |
| Retry/replay | | | | | | | | | | | | | | | X | | - | | |
| Identity mapping | | | | | | | | | | | | | | | | | | - | |
| Webhook ownership | | | | | | | | | | | | | | | | | | X | - |
| Failure audit | | | | | | | | | | | | X | | | | | | | - |

Notes: "Usage contract" depends on the event schema, idempotency, reversal, retry/replay and identity mapping (its
approval is the umbrella). Webhook ownership depends on identity mapping only in option B.

---

## Part C: Implementation impact matrix

| Decision | Repositories | Modules and files | APIs | Models | Migrations |
|---|---|---|---|---|---|
| D1 | Dealsflo | `table_inventory.py`, `data_classification.py`, `privacy_execution.py` | none | none | none |
| D4 | Dealsflo | `privacy_execution.py`, `privacy_maintenance.py`, `RetentionPolicy` rows | none | `RetentionPolicy` (values) | none |
| D7 | Dealsflo; deployment | `outbox/runtime.py`, `outbox/worker.py`, maintenance modules | `worker --serve` | none | none |
| D8 | Dealsflo | `audit/independent.py`, audit FKs, test cleanup | none | `AuditEvent` triggers | one (trigger, `DELETE`) |
| D9 | Dealsflo | `privacy_execution.py`, contact and deal models | privacy request endpoints (existing) | free-text columns | none unless columns change |
| D11 | Dealsflo | `documents/service.py`, storage, `config.py`, `provider_secrets` pattern | document upload and download (existing) | key id per object | one (key id column) |
| D13 | Dealsflo | `imports/service.py`, `imports/processing_service.py`, `privacy_execution.py` | import endpoints (existing) | import batch and source | none unless retention fields added |
| AI actor key | Dealsflo | `authz/permissions.py`, `execution_gate.py`, `policy.py`, role provisioning | role matrix | none | none |
| AI entitlement keys | SIBVO; Dealsflo | SIBVO catalogue; `capabilities.py`, `policy.py`, snapshot | `/sso/organization-entitlements` (existing) | none | possibly SIBVO mapping |
| Channel keys | Dealsflo | `authz/permissions.py`, `channel_policy.py`, `execution_gate.py` | none until gateway | none | none |
| Role grants | Dealsflo | `authz/`, `team/`, role UI | team endpoints (existing) | role assignments | none |
| Fail-closed | Dealsflo | `org_entitlement.py`, `policy.py` | none | none | none |
| Usage contract | SIBVO; Dealsflo | SIBVO ingestion; Dealsflo usage client, outbox event type | new SIBVO endpoint | SIBVO usage table | SIBVO migration |
| Event schema | SIBVO; Dealsflo | ingestion parser; producer | SIBVO ingestion | none | none |
| Idempotency | SIBVO | ingestion store | SIBVO ingestion | unique key (and hash) | SIBVO migration |
| Reversal | SIBVO; Dealsflo | reconciliation; `usage_ledger.reverse` | SIBVO ingestion | reversal reference | SIBVO migration |
| Retry/replay | Dealsflo; SIBVO | `outbox/service.py`, `outbox/replay.py`, reconciliation job | operator replay (existing tool) | `outbox_replay_record` (existing) | none |
| Identity mapping | Dealsflo; SIBVO | `sibvo_client.py`, organization model | snapshot (existing) | none (option A) | none (option A) |
| Webhook ownership | SIBVO; Dealsflo | SIBVO billing module; Dealsflo `billing/` | `/api/v1/billing/audit/reconciliations` (existing, read-only) | `BillingWebhookEvent`, `BillingReconciliationRecord` | none (option A) |
| Failure audit | Dealsflo | `org_entitlement.py`, audit module | none | `AuditEvent` rows | none |

---

## Part D: Decision-to-test traceability matrix

Existing tests are named as they exist on `develop`. "New" means the test is required and does not exist yet.

| Decision | Existing tests | New tests required |
|---|---|---|
| D1 | `test_table_inventory.py` | Every personal-data table in the export inventory or with a not-covered reason |
| D4 | `test_privacy_audit_independence.py`, `test_privacy_controls.py` | Per category with a period: expired rows deleted, held rows skipped, audit written |
| D7 | `test_provider_health.py` (serve cycle) | End-to-end `main()` for each maintenance job; a failed job does not stop others |
| D8 | `test_migration_independent_audit.py`, `test_privacy_audit_independence.py` | `DELETE` refused; `SET NULL` on user and organization delete still works; bypass unavailable outside tests |
| D9 | `test_privacy_controls.py`, `test_privacy_execution.py` | Per approved field: cleared on delete; untouched under legal hold; financial record untouched |
| D11 | `test_provider_secrets.py` (pattern) | Round trip; tampered ciphertext rejected; rotation re-encrypts; plaintext never stored; wrong-tenant key refused |
| D13 | `test_import_processing_api.py`, `test_import_result_security.py` | Export includes source files for the owning organization only; batch deletion respects holds |
| AI actor key | `test_channel_send_authorization.py` (uses the same seam) | Catalogue contains the key; member without it refused; owner behaviour per key status; cross-organization denial |
| AI entitlement keys | `test_org_entitlement_snapshot.py` (golden vector) | Per capability granted, denied when disabled, denied when missing |
| Channel keys | `test_channel_send_authorization.py` | Send key with consent and policy; configuration-only role refused |
| Role grants | `test_owner_only_authorization.py` | Self-grant refused; cross-organization assignment refused; audit per grant |
| Fail-closed | `test_org_entitlement_snapshot.py`, `test_entitlement_lifecycle.py`, WP-E13-next downgrade tests | Any grace period: granted within, denied after, revocation still denied |
| Usage contract | none (SIBVO side not built) | Dealsflo outbox delivery to a fake SIBVO; duplicate delivery; forged event rejected |
| Event schema | snapshot version tests | Unknown version rejected; additive field tolerated; event golden vector |
| Idempotency | `test_usage_ledger.py` (Dealsflo ledger) | Repeat returns same result; conflicting repeat refused and audited |
| Reversal | `test_usage_reversal_audit.py` | Reversal references own event only; applied once; net usage correct |
| Retry/replay | `test_outbox.py`, `test_outbox_worker_operations.py` | Attempt limit dead-letters; replay audited; reconciliation reports seeded mismatch |
| Identity mapping | `test_org_entitlement_snapshot.py` (cross-organization rejected) | Unmapped organization denied (option B only) |
| Webhook ownership | `test_billing_audit_endpoints.py`, `test_billing_reconciliation_service.py` | Option A: no Dealsflo path stores billing payloads; option B: signed forward verified, replay once |
| Failure audit | `test_privacy_audit_independence.py` (pattern) | Access-change episode written once; no secret in metadata; outage logged without response body |

---

## Part E: Prioritized decision sequence

Ordered by what unblocks the most work without contradicting another decision.

1. **Standing mapping and fail-closed (no decision needed; confirm).** Confirm the ID mapping above and the current
   fail-closed behaviour. Zero build cost.
2. **Webhook ownership.** Settles whether Dealsflo stores billing payloads at all. Changes the scope of the
   "replay through endpoint" objective and the reconciliation models.
3. **Identity mapping.** Confirm Option A. Required before any usage event is attributed.
4. **Event schema, idempotency and reversal** (one SIBVO review). Shapes the usage contract before SIBVO builds it.
5. **Usage-ingestion contract** (umbrella approval, split into 053a and 053b).
6. **AI entitlement keys** (confirm `ai_gateway` or split). Needed before any AI capability can be sold per plan.
7. **AI actor permission key and role grants.** Together, they decide who may run AI at all.
8. **Channel keys.** After ADR-0028 is accepted.
9. **D1, then D9, then D4.** Classification, then export and deletion scope, then retention periods. Each depends on the
   previous one.
10. **D13.** After D4 sets document retention.
11. **D7.** Deployment decision; can run in parallel with 1 to 8 because it does not depend on them.
12. **D8.** After D4 and D12; delivered as the two-step change in its recommendation.
13. **D11.** Independent of the rest; delivered as option B now, with the managed key later.
14. **Failure audit and retry/replay.** After 5, since both depend on the usage path.

---

## Part F: Blocking versus safe-to-wait

### Decisions that block E13 completion

These must be decided before the named criterion can be Met. Each has no workaround that keeps the criterion honest.

| Decision | Criteria it blocks |
|---|---|
| Usage-ingestion contract (with event schema, idempotency, reversal, retry/replay, identity mapping) | DFR1-053 usage summaries and reconciled usage |
| AI actor permission key and role grants | DFR1-006 "no optional AI executes unless all gates pass" end to end; DFR1-015 cannot be verified |
| AI capability entitlement keys (DFR1-005) | DFR1-006 entitlement criterion; DFR1-036 entitlement and enablement |
| D4 retention periods | DFR1-050 retention criterion for categories other than documents and invitations |
| D1 and D9 classification and deletion scope | DFR1-050 deletion and export for the remaining categories |
| Channel keys (with ADR-0028) | Communication epics; DFR1-006 channel gate end to end |

### Decisions that can safely wait

These do not block a backlog criterion as written, or their current safe default is correct and tested.

| Decision | Why it can wait |
|---|---|
| D7 deployment scheduler | Code paths exist and are tested. Waiting leaves maintenance unscheduled, which is disclosed; it does not make the criteria false, but it keeps DFR1-017 and DFR1-050 jobs Partial. Note: DFR1-050 "retention jobs auditable" is Met where jobs run. |
| D8 audit deletion path | `UPDATE` is blocked; the gap is `DELETE`. Disclosed as a limitation. |
| D11 encryption at rest | Not a backlog acceptance criterion for DFR1-050. Disclosed as a known limitation. |
| D13 import retention | Import files are kept with their batch; disclosed as a gap for data-subject requests. |
| Fail-closed grace period | Current behaviour is safe and matches the contract. No grace period is needed unless a business need exists. |
| Role-granting beyond owner | Owner-only is safe. Delegation is a usability decision. |
| Webhook ownership (option A cleanup) | Dealsflo stores no billing payloads today. The models are inert. |
| Failure audit (option B) | Denials are already visible through tests and the snapshot; the audit trail is an improvement. |

---

## Part G: What this document does not change

- No story status changes. DFR1-006, DFR1-017, DFR1-050 remain Partial; DFR1-053 remains Blocked; E13 is not Done.
- No code, migration, permission, entitlement key, endpoint or configuration is added or changed.
- No decision above is approved. Each is awaiting its named owner.
- E06 and every other epic remain untouched.
