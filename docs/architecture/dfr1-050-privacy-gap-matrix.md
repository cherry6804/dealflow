# DFR1-050 privacy gap matrix

Status of this document: final for the implementation on `feature/DFR1-050-privacy-retention-export-deletion`, based on `origin/develop` at `71ea9d9`. It records what each approved decision (A to L) requires, what the code does, and the justified final status of every database table. It does not redefine any decision.

The per-table section at the end is generated from `backend/app/governance/table_inventory.py` and the clearing rules in `backend/app/governance/privacy_derived.py`. Regenerate it after changing either file.

## Reused foundations

`app/governance/privacy.py` (request records, versioned retention, legal holds, eligibility), `privacy_execution.py` (export, deletion, retention, download), `privacy_maintenance.py` (scheduled expiry and retention), `data_classification.py` (category register), `table_inventory.py` (one disposition per table), the outbox, the independent audit log, and the approval service. The new module `privacy_derived.py` holds data mapping only: clearing rules and exporters for derived records. It is not a service.

## Acceptance matrix

| # | Requirement (decision) | Final status | Evidence |
|---|---|---|---|
| 1 | Export all applicable organization-owned CRM categories (A) | Met. Contacts, leads, follow-ups, activities, profiles, requirements with locations, preferences and history, deals with milestones, commissions, negotiations and stage history, properties, referrals, site visits, requirement matching runs, results, shortlists and next-best actions, notifications and preferences, consent records, do-not-disturb records, membership removals, lead intake, lead qualification and lead priority | `test_privacy_dfr1050.py::test_export_includes_properties…`, `test_site_visits_referrals…`, `test_privacy_derived.py::test_lead_intake_and_priority…` |
| 2 | Export coverage and manifest: included, excluded, reasons, unbuilt producers, SIBVO-owned data and route (A) | Met. The manifest is built from the register and the inventory: `exported`, `not_exported`, `not_covered` (every non-exported table with its reason), `not_implemented_categories`, `sibvo_owned`, `sibvo_privacy_route` | `test_manifest_discloses_sibvo_owned_data…`, `test_the_manifest_not_covered_list_matches_the_inventory`, `test_every_producing_category_is_exported_or_explicitly_excluded` |
| 3 | Identifiers and relationships kept (A) | Met. Links are exported as identifiers; sub-records sit under their parent category | Export tests for properties, requirement matching, agent steps, workflow steps |
| 4 | CRM free text cleared (B) | Met for every approved field in `CLEARING_RULES` (see the generated classification below). Structure, identifiers, statuses and counts are kept | `test_crm_free_text_is_cleared_and_the_structure_is_kept`, `test_lead_intake_and_priority…`, `test_human_tasks…`, `test_agent_run_deletion…` |
| 5 | Financial, contractual and mandatory records kept (B, G) | Met. Commission terms, payment notes and references, AI cost entries and billing records are not changed | `test_crm_free_text…` (commission terms kept); `ai.usage` and `billing.records` are mandatory |
| 6 | Contact deferral while dependencies remain (C) | Met (existing). Repeated runs are consistent | `test_privacy_execution.py` deferral tests |
| 7 | Document object and row removed as one controlled operation (D) | Met. Rows are removed first and objects after the flush. A failed object removal rolls the rows back | `test_a_failed_object_removal_rolls_the_document_row_back` |
| 8 | Import-batch files in the document policy (D) | Met for the file: exported, then removed, then the source name is cleared. The batch row is kept because contacts reference it with `ON DELETE RESTRICT`. Reported as `deleted_partial`, never as full deletion | `test_import_attachment_*` |
| 9 | Deletion evidence without personal content (D, G) | Met. Audit records carry counts, outcomes and kept-field names, never the cleared values | `test_a_deletion_writes_counts_and_outcomes_but_no_personal_text` |
| 10 | No secrets, credentials, prompts or internal configuration exported (E, G) | Met. Agent and workflow definitions and versions, agent prompts (`instructions`), idempotency keys, provider credentials, webhook secrets and rate-limit counters are never exported | `test_agent_runs_are_exported…`, `test_export_never_contains_credentials…` |
| 11 | SIBVO-owned data not changed by Dealsflo, and disclosed (F) | Met. Memberships, subscriptions, plans, entitlements, identity links, platform billing and users are `sibvo_owned` and never changed | `test_manifest_discloses…` |
| 12 | Audit and mandatory records kept, not deleted (G) | Met. `audit_events`, `billing_*`, AI usage and cost records are never deleted by a customer request. Audit evidence is not in ordinary exports | Register and inventory tests |
| 13 | Legal holds block deletion and clearing, not export; checked at request and before each category (H) | Met. `evaluate_deletion` is checked at request time and again in the executor before each category | `test_a_legal_hold_placed_after_the_request_blocks_the_execution`, `test_a_legal_hold_keeps_agent_run_inputs_in_place` |
| 14 | Hold create, release and enforcement audited (H) | Met (existing) | `test_privacy_controls.py` |
| 15 | Export permission, audit, private storage, expiry and download checks (I) | Met (existing). Creation and download use `governance.privacy.manage`. A reader without it gets 403 | `test_an_export_of_derived_records_is_refused_without_the_manage_permission`, existing export tests |
| 16 | Explicit deletion confirmation (J) | Met. Creation and execution both require `confirm: true` | `test_execute_endpoint_requires_confirmation_and_the_manage_permission` |
| 17 | Authorized step before destructive execution (J) | Met with a stated interpretation. Execution is an explicit, audited step by a holder of `governance.privacy.manage`, validated by state. It is not a second approver. See decision 1 | `test_a_recorded_deletion_queues_nothing_until_it_is_explicitly_executed`, `test_execution_is_refused_once_the_deletion_has_run` |
| 18 | Background processing actually runs (A, J) | Met. Export creation queues processing. Deletion queues processing only through the execute step | `test_creating_an_export_queues_its_processing` |
| 19 | Idempotent execution and recoverable failure (J) | Met. The processing handler is a no-op outside the first state. A repeated execute queues one event (idempotency key). A failed category rolls back and leaves the request open | `test_execution_is_refused_once_the_deletion_has_run`, rollback test |
| 20 | No retention periods invented (K) | Met. Policies without a period are `no_period`. Only documents and invitations are enforced | Existing retention tests |
| 21 | Retention runs audited with policy version, time, scope, counts and outcome (K) | Met. Each enforcement event carries `policy_version`, `retention_days`, `cutoff` and the outcome | `test_a_retention_run_records_the_policy_version_it_applied` |
| 22 | Scheduler absence is not presented as enforcement (K) | Met. The maintenance module says nothing schedules it. No test or report implies automation | Module docstring; existing maintenance tests |
| 23 | Unbuilt producers registered, not faked (L) | Met. `messaging.conversations`, `voice.call_records`, `voice.transcripts` and `ai.prompts_and_responses` are `producer_exists=False` and listed as not implemented | `test_manifest_discloses…` |
| 24 | Secrets and personal text not logged (Logging) | Met. Maintenance logs the exception type only. Outbox `last_error` stores the type only | `test_outbox_failure_text…`, `test_a_failed_retention_organization_logs…` |
| 25 | Ruff clean, no SQLAlchemy warnings in privacy code | Met. Ruff passes on changed files. The `distinct()` warning is fixed | Lint and the regression run |

## Decisions for the product owner

1. **Deletion approval.** Implemented as an explicit, audited execute step by a privacy administrator, validated by request state and re-checked against holds. No second approver is added. Please confirm this reading of "authorized approval" (decision J).
2. **Import batch rows.** The file is removed, the source name is cleared, and the batch row is kept because contacts reference it. Please confirm this is acceptable.
3. **Requirement history snapshots** and **requirement tables** have no approved free-text field. Their content is kept for version integrity. Please confirm.
4. **Lead intake fingerprint.** `payload_hash` stays after deletion, as duplicate-detection evidence. It is a hash of the submitted data. Please confirm that a hash is acceptable to keep.
5. **Human task events are append-only, and this story does not change that.** The database trigger
   `trg_human_task_events_immutable` fires `BEFORE UPDATE OR DELETE` on the whole table, with no column exception.
   Deletion therefore cannot clear or remove any event. What each event holds, and how each is treated:
   - Decision and assignment events (`created`, `assigned`, `reassigned`, `approved`, `rejected`, `expired`,
     `cancelled`) are mandatory approval evidence. They are retained.
   - Comment events (`comment`) and the decision comments they carry can contain personal information. They are
     ordinary operational history, but they are append-only, so they are retained as well.
   The export includes events for the data subject. Deletion reports them as `retained`. It never reports them as
   deleted or anonymized. The task rows themselves are cleared (title, instructions, decision comment), and the
   category outcome is `anonymized_partial`. Redacting events would mean changing the immutability control, which is an
   audit-integrity decision for the product owner and security. This story does not make that change.

## Unsupported categories (not implemented, classified explicitly)

- Messages and conversations, voice call records, call transcripts and recordings: no producer exists. They are registered with `producer_exists=False`, appear in every manifest as not implemented, and must not be reported as checked.
- AI chat prompts and responses: no conversational producer is persisted. Agent run outputs are exported under `ai.execution_traces`.
- Provider-side deletion: no provider integration exists, so no deletion is claimed at a provider.

Retention periods are not invented. No data is deleted automatically, and no scheduler is configured by this change.

## Table-by-table classification (generated)

All 92 database tables appear once, from `app/governance/table_inventory.py`. This section is generated from the inventory and clearing rules, so it cannot drift from the code.

| Table | Ownership | Export | Deletion / retention | Reason |
|---|---|---|---|---|
| `activities` | Dealsflo organization-owned | exported (crm.follow_ups) | fields cleared: title, description, details |  |
| `agent_execution_steps` | Dealsflo organization-owned | exported (ai.execution_traces) | fields cleared: trace |  |
| `agent_executions` | Dealsflo organization-owned | exported (ai.execution_traces) | fields cleared: input_values, output, failure_reason |  |
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
| `customer_requirement_history` | Dealsflo organization-owned | exported (crm.requirements) | - |  |
| `customer_requirement_locations` | Dealsflo organization-owned | exported (crm.requirements) | - |  |
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
| `import_batches` | Dealsflo organization-owned | file exported under documents.files; row not exported | file removed; source name cleared; row kept (contacts reference it) | Uploaded file: exported and removed under documents.files. Batch row kept: imported contacts reference it (DFR1-050). |
| `inbound_webhook_deliveries` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Delivery evidence: outcome, reason code and hashes. Accepted deliveries keep a redacted envelope. Security evidence, not customer data. Not exported. |
| `inbound_webhook_endpoints` | Dealsflo (secret or credential) | not exported | not customer-deleted (never exported) | Inbound webhook endpoint configuration with an encrypted signing secret. Never exported; the secret is shown once at creation or rotation. |
| `knowledge_chunks` | Dealsflo organization-owned | exported (ai.embeddings) | deleted on request |  |
| `lead_intake_submissions` | Dealsflo organization-owned | exported (crm.lead_intake) | fields cleared: raw_payload, normalized_payload, validation_problems, decision_reason |  |
| `lead_priority_corrections` | Dealsflo organization-owned | exported (crm.lead_intelligence) | fields cleared: reason |  |
| `lead_priority_scores` | Dealsflo organization-owned | exported (crm.lead_intelligence) | fields cleared: factors, requirement_summary |  |
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
| `requirement_match_runs` | Dealsflo organization-owned | exported (crm.requirement_matching) | fields cleared: criteria_snapshot |  |
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
| `workflow_executions` | Dealsflo organization-owned | exported (automation.workflow_runs) | fields cleared: input_values, output, failure_reason |  |
| `workflow_lifecycle_events` | Dealsflo organization-owned | not exported | not customer-deleted (governance record) | Workflow lifecycle history: publish, pause, resume and rollback with the acting member and a reason. Governance evidence of configuration changes. Not exported to customers. |
| `workflow_versions` | Dealsflo organization-owned | not exported | not customer-deleted (configuration) | Immutable published workflow versions and their configuration. Never updated or deleted. |

Totals: exported 46, file exported under documents.files; row not exported 1, not exported 45.
