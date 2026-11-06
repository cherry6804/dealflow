# DFR1-050 privacy gap matrix

Status: final for `feature/DFR1-050-privacy-retention-export-deletion`, based on `origin/develop` at `71ea9d9`. Records what each approved decision requires, what the code does, and the justified final status of every database table. It does not redefine any decision.

The per-table section at the end is generated from `backend/app/governance/table_inventory.py` and the clearing rules in `backend/app/governance/privacy_derived.py`. Regenerate it after changing either file.

## Reused foundations

`app/governance/privacy.py` (request records, versioned retention, legal holds, eligibility), `privacy_execution.py` (export, deletion, retention, download), `privacy_maintenance.py` (scheduled expiry and retention), `data_classification.py` (category register), `table_inventory.py` (one disposition per table), the outbox, the independent audit log, and the approval service. `privacy_derived.py` holds data mapping only: clearing rules, tombstones, exporters and the manifest's limitation statements. It is not a service.

## Final decisions

1. **Human task events: resolved, retained.** `human_task_events` is append-only. The database trigger `trg_human_task_events_immutable` fires `BEFORE UPDATE OR DELETE` on the whole table, with no column exception. Privacy processing does not bypass it. Decision and assignment events (`created`, `assigned`, `reassigned`, `approved`, `rejected`, `expired`, `cancelled`) are mandatory approval evidence. Comment events (`comment`) and the decision comments they carry are retained personal-data history: they can contain personal information, and they are part of the same append-only record. The export includes them for the data subject, and the manifest states the limitation under `retained_personal_data_history` and `limitations`. Deletion reports them as `retained`, never as deleted or anonymized. Any future redaction needs a separately approved security design. The task rows themselves are cleared.

2. **Deletion approval: resolved, no second approver for Release 1.** Deletion uses the explicit, audited execution step. The step requires `confirm: true` at creation and at execution, and `governance.privacy.manage` for both. It validates request state (`eligibility_recorded` only). Legal holds are re-checked before each category runs, so a hold placed after the request still blocks it. Each execution request writes an audit event (`privacy.deletion.execution_requested`) with the acting member. A reader without the permission gets 403 and the request does not change.

3. **Import batch rows: resolved, minimum technical record.** A batch that holds a stored file, a file name, or a per-row error summary is cleared. The file is removed. The source name is replaced with `Redacted`. The error summary, which can echo row values, is set to null. The batch keeps only: id, organization, source format, content type, file size, status, row counts, timestamps, and an empty storage reference. The row is kept because contacts reference it with `ON DELETE RESTRICT`. A batch whose file was removed earlier is still cleared. Other organizations' batches are untouched. Outcome: `deleted_partial`.

4. **Requirement history and requirement tables: resolved, corrected in review.** Every string column on the five requirement tables was reviewed against the models. Status, budget, transaction type, property type, possession and parking codes and change type are business terms or codes, and they are kept. City and locality are place names that a customer asked for. Once linked to an identifiable customer through the lead or profile, they reveal where that person wants to live, so they are personal data. Deletion replaces them with the placeholder on the current location rows and inside the location entries of history snapshots. Version, change type and timestamps are kept. Budget and property preferences are kept as the commercial terms of the requirement. That is a judgment the product owner should confirm. The test `test_requirement_string_columns_are_the_reviewed_codes_and_places_only` fails if a new string column is added without review. Deletion of `crm.requirements` reports `anonymized_partial`, and the kept fields are listed in the execution record.

5. **Lead intake fingerprint: resolved, replaced on deletion.** `payload_hash` is a SHA-256 of the normalized submission, which includes contact details, and it is unsalted. A digest of a phone number or an email can be checked against guessed values, so while the submission exists it can identify the person. It is therefore replaced on deletion by a tombstone computed from the row id, table and field name only. The original digest is not kept anywhere in the row. The raw payload, normalized payload, validation problems and decision reason are cleared, and the external reference is replaced by `redacted-<id>`, which keeps its uniqueness constraint. Live submissions keep their digest for duplicate detection. Tests: `test_lead_intake_deletion_replaces_the_digest…`, `test_no_stored_row_keeps_the_original_digest_after_deletion`.

   The same reasoning applies to other digests computed from content that is cleared: `agent_executions.input_hash`, `workflow_executions.input_hash`, `lead_priority_scores.input_hash`, `requirement_match_runs.input_hash`. Each is replaced with a tombstone when its content is cleared (test: `test_agent_run_and_lead_score_digests_are_replaced_on_clearing`). `lead_priority_scores` and `requirement_match_runs` hash business facts together with an identifier and no contact details; they are replaced anyway, to keep one rule.

6. **Unbuilt producers: resolved, classified as unsupported.** Messages and conversations, calls, voice recordings, transcripts, and AI chat prompts and responses have no producer in the codebase. They are registered with `producer_exists=False`, listed as not implemented in every manifest, and stated as unsupported under `limitations`. Nothing is exported from them, nothing is deleted from them, and no privacy lifecycle is claimed for them. Agent run content is exported under `ai.execution_traces`. No provider-side deletion exists, and none is claimed.

## Retention

No retention period has been approved for any category except the two that were already enforced (documents, invitations), and those run only where an organization administrator has configured a period. No automatic destructive deletion is enabled. No scheduler is configured by this change.

## Acceptance matrix

| # | Requirement (decision) | Final status | Evidence |
|---|---|---|---|
| 1 | Export all applicable organization-owned CRM and derived categories (A) | Met | export tests in `test_privacy_dfr1050.py`, `test_privacy_derived.py` |
| 2 | Coverage manifest: included, excluded, reasons, unbuilt producers, SIBVO-owned data and route, limitations, retained history (A) | Met, derived from the inventory and the limitation constants | `test_manifest_discloses…`, `test_manifest_states_the_human_task_limitation…`, `test_the_manifest_not_covered_list_matches_the_inventory` |
| 3 | Identifiers and relationships kept (A) | Met | export tests |
| 4 | Personal free text cleared; structure and financial values kept (B) | Met, per rule and verified after clearing | `test_crm_free_text…`, `test_lead_intake_and_priority…`, `test_human_tasks…`, `test_agent_run_deletion…` |
| 5 | Financial, contractual and mandatory records kept (B, G) | Met | commission terms kept in `test_crm_free_text…`; AI cost entries and billing records not cleared |
| 6 | Contact deferral (C) | Met (existing) | `test_privacy_execution.py` |
| 7 | Document object and row removed as one controlled operation, with rollback on failure (D) | Met | `test_a_failed_object_removal_rolls_the_document_row_back` |
| 8 | Import batch rows minimised; names, filenames and error text cleared (D, decision 3) | Met | `test_import_batch_deletion_clears…`, `test_a_batch_whose_file_was_already_removed…`, `test_import_batches_of_another_organization…` |
| 9 | Deletion evidence without personal content (D, G) | Met | `test_a_deletion_writes_counts_and_outcomes_but_no_personal_text` |
| 10 | No secrets, credentials, prompts or internal configuration exported (E, G) | Met | `test_agent_runs_are_exported…`, `test_export_never_contains_credentials…` |
| 11 | SIBVO-owned data not changed and disclosed (F) | Met | `test_manifest_discloses…` |
| 12 | Audit and mandatory records kept (G) | Met | register and inventory tests |
| 13 | Legal holds block clearing and deletion, not export; checked at request and before each category (H) | Met | `test_a_legal_hold_placed_after_the_request_blocks_the_execution`, `test_a_legal_hold_keeps_agent_run_inputs_in_place`, `test_a_legal_hold_blocks_human_task_clearing_and_task_fields_stay` |
| 14 | Hold create, release and enforcement audited (H) | Met (existing) | `test_privacy_controls.py` |
| 15 | Export permission, audit, private storage, expiry and download (I) | Met (existing) and tested for derived records | `test_an_export_of_derived_records_is_refused…` |
| 16 | Explicit confirmation (J) | Met | `test_execute_endpoint_requires_confirmation_and_the_manage_permission` |
| 17 | Explicit, audited, authorized execution step; no second approver for Release 1 (J, decision 2) | Met | `test_execute_is_refused_for_a_user_without_the_manage_permission`, `test_execution_request_is_audited_with_the_acting_member`, `test_a_recorded_deletion_queues_nothing…` |
| 18 | Background processing actually runs (A, J) | Met | `test_creating_an_export_queues_its_processing` |
| 19 | Idempotent execution and recoverable failure (J) | Met | `test_execution_is_refused_once_the_deletion_has_run`, rollback test |
| 20 | No retention periods invented (K) | Met | retention tests; limitation text |
| 21 | Retention runs audited with policy version (K) | Met | `test_a_retention_run_records_the_policy_version_it_applied` |
| 22 | Scheduler absence not presented as enforcement (K) | Met | module docstring; limitation text |
| 23 | Unbuilt producers registered, not faked (L) | Met | `test_manifest_states…` |
| 24 | Secrets and personal text not logged; outbox text redacted (Logging) | Met | `test_outbox_error_redaction.py`, `test_a_failed_retention_organization_logs…` |
| 25 | Lint and migrations | Met for changed files; no migration added | see the report |
| 26 | Human task events retained, reported as retained (decision 1) | Met | `test_human_tasks_and_events_are_exported_and_cleared_on_deletion` |
| 27 | Lead intake digest replaced; agent and score digests replaced on clearing (decision 5) | Met | `test_lead_intake_deletion_replaces…`, `test_agent_run_and_lead_score_digests…` |
| 28 | Requirement tables reviewed; city and locality replaced; business terms and history kept; evidence tests (decision 4) | Met | `test_requirement_string_columns_are_the_reviewed…`, `test_requirement_history_survives…` |

## Retained and excluded data

- **Retained, personal content present:** human task comment and decision text (decision 1); import batch rows, technical fields only (decision 3); requirement business history and locations (decision 4).
- **Retained, mandatory:** audit events, billing and reconciliation records, AI usage and cost entries, approval records, privacy request records.
- **Replaced or removed:** submission digests and references (decision 5); input digests on cleared records; import file names, error text and stored files (decision 3).
- **Excluded from export:** agent and workflow definitions and prompts; idempotency keys; provider and webhook secrets; webhook delivery evidence; rate-limit counters; workflow lifecycle history.

## Limitations that remain

- Human task comment text cannot be redacted without a separately approved security design (decision 1).
- Messages, calls, recordings, transcripts and AI chat content have no producer and are unsupported (decision 6).
- No provider-side deletion exists; deletion is limited to Dealsflo's own records.
- Retention periods are not approved for most categories, so they are not enforced.
- Live submissions and live records keep their digests until deletion, for duplicate detection and audit.
- Budget and property preferences linked to a customer are kept as business terms. The product owner should confirm this (decision 4).

## Table-by-table classification (generated)

All 92 database tables appear once, from `app/governance/table_inventory.py`. This section is generated from the inventory and clearing rules, so it cannot drift from the code.

| Table | Ownership | Export | Deletion / retention | Reason |
|---|---|---|---|---|
| `activities` | Dealsflo organization-owned | exported (crm.follow_ups) | fields cleared: title, description, details |  |
| `agent_execution_steps` | Dealsflo organization-owned | exported (ai.execution_traces) | fields cleared: trace |  |
| `agent_executions` | Dealsflo organization-owned | exported (ai.execution_traces) | fields cleared: input_values, output, failure_reason, input_hash |  |
| `agent_versions` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Immutable published agent configurations, instructions and validation snapshots. Internal configuration. Never exported. |
| `agents` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Agent definitions: name, description, instructions and the draft configuration. Internal configuration and prompts. Never exported. |
| `ai_provider_cost_entries` | Dealsflo organization-owned | exported (ai.usage) | mandatory financial record: not deleted |  |
| `ai_provider_prices` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Platform provider price versions. Configuration, not customer data. |
| `ai_task_routes` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Provider and model choice per AI task. Holds no credential. |
| `ai_usage_events` | Dealsflo organization-owned | exported (ai.usage) | mandatory financial record: not deleted |  |
| `approval_requests` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Approval evidence with actor identifiers. |
| `audit_events` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Security and governance records. Never deleted by a request. |
| `auth_login_rate_limits` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Login throttling state. |
| `auth_sessions` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Session credentials. |
| `automation_executions` | Dealsflo organization-owned | exported (automation.rule_runs) | fields cleared: action_results, error_message |  |
| `automation_rules` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Rule definitions. |
| `billing_reconciliation_records` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Financial records. Export excluded by decision D3. |
| `billing_webhook_events` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Financial records. Export excluded by decision D3. |
| `channel_policies` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Channel configuration. |
| `contact_consent_records` | Dealsflo organization-owned | exported (crm.contacts) | - |  |
| `contact_do_not_disturb` | Dealsflo organization-owned | exported (crm.contacts) | - |  |
| `contacts` | Dealsflo organization-owned | exported (crm.contacts) | - |  |
| `customer_profiles` | Dealsflo organization-owned | exported (crm.customer_profiles) | fields cleared: customer_notes |  |
| `customer_requirement_history` | Dealsflo organization-owned | exported (crm.requirements) | city and locality inside snapshot locations replaced; version, change type and timestamps kept |  |
| `customer_requirement_locations` | Dealsflo organization-owned | exported (crm.requirements) | city and locality replaced; row kept |  |
| `customer_requirement_possession_parking_preferences` | Dealsflo organization-owned | exported (crm.requirements) | - |  |
| `customer_requirement_property_preferences` | Dealsflo organization-owned | exported (crm.requirements) | - |  |
| `customer_requirements` | Dealsflo organization-owned | exported (crm.requirements) | - |  |
| `deal_commissions` | Dealsflo organization-owned | exported (crm.deals) | - |  |
| `deal_negotiation_history` | Dealsflo organization-owned | exported (crm.deals) | fields cleared: note |  |
| `deal_negotiations` | Dealsflo organization-owned | exported (crm.deals) | - |  |
| `deal_stage_history` | Dealsflo organization-owned | exported (crm.deals) | fields cleared: reason |  |
| `deals` | Dealsflo organization-owned | exported (crm.deals) | fields cleared: notes |  |
| `document_reviews` | Dealsflo organization-owned | exported (documents.files) | removed with its document (reviews); mandatory financial record (cost entries) |  |
| `documents` | Dealsflo organization-owned | exported (documents.files) | removed with its document (reviews); mandatory financial record (cost entries) |  |
| `email_outbox_messages` | Dealsflo organization-owned | not exported | outside organization deletion (D5) | Platform email outbox. No organization column. Excluded by decision D5. |
| `email_verification_tokens` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Single-use token material. |
| `execution_rate_limit_windows` | Platform / system | not exported | not customer-deleted (platform record) | Rate-limit counters keyed by an actor identifier. System operational state with no customer content. |
| `follow_ups` | Dealsflo organization-owned | exported (crm.follow_ups) | fields cleared: title, description |  |
| `human_task_events` | Dealsflo organization-owned | exported (automation.human_tasks) | retained: mandatory approval evidence and comment history (append-only, not altered) |  |
| `human_tasks` | Dealsflo organization-owned | exported (automation.human_tasks) | fields cleared: title, instructions, decision_comment |  |
| `import_batches` | Dealsflo organization-owned | file exported under documents.files; row not exported | file removed; source name and error text cleared; technical fields kept (contacts reference the row) | Partially covered. The uploaded file is exported and removed under documents.files. The file name, the error summary and any personal text are cleared. Only a minimal technical record is kept: identifiers, organization, source format, content type, file size, status, row counts and timestamps. The row stays because imported contacts reference it with ON DELETE RESTRICT (DFR1-050). |
| `inbound_webhook_deliveries` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Delivery evidence: outcome, reason code and hashes. Accepted deliveries keep a redacted envelope. Security evidence, not customer data. Not exported. |
| `inbound_webhook_endpoints` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Inbound webhook endpoint configuration with an encrypted signing secret. Never exported; the secret is shown once at creation or rotation. |
| `knowledge_chunks` | Dealsflo organization-owned | exported (ai.embeddings) | deleted on request |  |
| `lead_intake_submissions` | Dealsflo organization-owned | exported (crm.lead_intake) | fields cleared: raw_payload, normalized_payload, validation_problems, decision_reason, external_reference, payload_hash |  |
| `lead_priority_corrections` | Dealsflo organization-owned | exported (crm.lead_intelligence) | fields cleared: reason |  |
| `lead_priority_scores` | Dealsflo organization-owned | exported (crm.lead_intelligence) | fields cleared: factors, requirement_summary, input_hash |  |
| `lead_qualification_results` | Dealsflo organization-owned | exported (crm.lead_qualification) | fields cleared: findings, review_reason |  |
| `leads` | Dealsflo organization-owned | exported (crm.leads) | fields cleared: next_action |  |
| `membership_roles` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Role assignment belongs to membership (D6). |
| `next_best_action_recommendations` | Dealsflo organization-owned | exported (crm.requirement_matching) | fields cleared: facts, summary, history |  |
| `notification_preferences` | Dealsflo organization-owned | exported (messaging.notifications) | - |  |
| `notifications` | Dealsflo organization-owned | exported (messaging.notifications) | - |  |
| `organization_capability_settings` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Switch settings and their change records. |
| `organization_entitlement_snapshots` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Entitlement snapshot received from SIBVO. Dealsflo does not change it (D6). |
| `organization_memberships` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Membership is owned by SIBVO (D6). |
| `organization_usage_alert_settings` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Configured alert thresholds. |
| `organization_usage_budgets` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Budget configuration and aggregate quantities. |
| `organizations` | Platform / system | not exported | not customer-deleted (platform record) | Tenant root record. |
| `outbox_events` | Platform / system | not exported | not customer-deleted (platform record) | Internal delivery queue. Carries no personal values by design. |
| `outbox_replay_records` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Operator replay evidence for outbox events. |
| `password_reset_tokens` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Single-use token material. |
| `payment_milestones` | Dealsflo organization-owned | exported (crm.deals) | - |  |
| `permissions` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Permission definitions. |
| `plan_entitlements` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Plan entitlements are owned by SIBVO. |
| `plans` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Plan definitions are owned by SIBVO. |
| `privacy_data_requests` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Privacy request evidence. |
| `privacy_legal_holds` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Legal hold evidence. |
| `privacy_retention_policies` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Retention configuration evidence. |
| `properties` | Dealsflo organization-owned | exported (crm.properties) | - |  |
| `provider_connections` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Connection metadata that references encrypted credentials. Never exported. |
| `provider_credentials` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Encrypted provider secret material. Never exported or returned. |
| `provider_verification_attempts` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Verification outcomes and reason codes only. Kept as evidence. |
| `referrals` | Dealsflo organization-owned | exported (crm.referrals) | - |  |
| `requirement_match_run_results` | Dealsflo organization-owned | exported (crm.requirement_matching) | - |  |
| `requirement_match_runs` | Dealsflo organization-owned | exported (crm.requirement_matching) | fields cleared: criteria_snapshot, input_hash |  |
| `requirement_property_shortlists` | Dealsflo organization-owned | exported (crm.requirement_matching) | - |  |
| `requirement_shortlist_events` | Dealsflo organization-owned | exported (crm.requirement_matching) | - |  |
| `role_permissions` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Role definitions. |
| `roles` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Role definitions. |
| `sibvo_identity_links` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Identity link maintained from SIBVO. |
| `sibvo_organization_links` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Organization link maintained from SIBVO. |
| `site_visits` | Dealsflo organization-owned | exported (crm.site_visits) | - |  |
| `subscriptions` | SIBVO | not exported | not changed by Dealsflo (SIBVO-owned) | Subscription state is owned by SIBVO (D6). |
| `team_invitations` | Dealsflo organization-owned | exported (team.invitations) | - |  |
| `team_member_removals` | Dealsflo organization-owned | exported (team.invitations) | - |  |
| `users` | Platform / system | not exported | not customer-deleted (platform record) | Account identity. Account deletion is a separate decision. |
| `workflow_definitions` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Workflow definition: name, description, draft configuration and lifecycle status. Organization-owned configuration with no personal data. |
| `workflow_execution_steps` | Dealsflo organization-owned | exported (automation.workflow_runs) | fields cleared: trace |  |
| `workflow_executions` | Dealsflo organization-owned | exported (automation.workflow_runs) | fields cleared: input_values, output, failure_reason, input_hash |  |
| `workflow_lifecycle_events` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Workflow lifecycle history: publish, pause, resume and rollback with the acting member and a reason. Governance evidence of configuration changes. Not exported to customers. |
| `workflow_versions` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Immutable published workflow versions and their configuration. Never updated or deleted. |

Totals: exported 46, file exported under documents.files; row not exported 1, not exported 45.
