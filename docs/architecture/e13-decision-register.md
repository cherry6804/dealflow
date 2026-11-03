# E13 decision register

Status: active. Owner of this file: the E13 release owner. Every entry names a question that only a named owner can
answer. Nothing here is decided by an engineer. Where code runs with a safe default, the default is stated, and the
default must not be read as an approved policy.

Rules applied in this register:

- No SIBVO endpoint, plan feature key, permission key, role grant, provider connection, legal policy or retention
  period is invented. Each one is listed as open until its owner approves it.
- Where an open decision blocks a story, the blocked acceptance criteria stay unmet and the story stays Partial or
  Blocked. A story is Done only when every criterion is met and verified.

## Register

| ID | Question | Recommended option | Impact if undecided | Current behaviour in code | Required owner |
|---|---|---|---|---|---|
| D1 | Clear free-text fields on deletion, or delete rows? | Clear only approved personal free-text fields. Scope in the architecture document, section 5.9. | Deletion of contacts and related free-text categories cannot run for those categories. | Nothing is cleared. These categories report `deletion_executor_not_built`. | Product and legal |
| D4 | Retention period per data category | Set a period per category with a recorded legal basis. | Retention runs only for documents and invitations. All other categories are kept. | No period is set for any category except those with an approved period. | Product and legal |
| D7 | Scheduler for `privacy_maintenance` and `usage_maintenance` | Scheduled jobs in the deployment environment, with alerting on failure. | Retention, reservation expiry and privacy deadlines are not enforced on a timer. | Neither job is scheduled. Both have `main()` entry points that run on demand. | Infrastructure |
| D8 | Audit immutability and a deletion path | Keep the `UPDATE` trigger. Add a `DELETE` trigger only with a controlled deletion path (retention-driven, audited, role-restricted). | Audit rows can be deleted directly. The `UPDATE` trigger is in place. | `UPDATE` is blocked by the trigger from migration `b4d8f2a6c1e9`. `DELETE` is allowed. A `DELETE` trigger is not added yet, because it would break the `ON DELETE SET NULL` foreign-key action on user and organization deletion, and the audit cleanup in tests. | Security and legal |
| D9 | Classification of remaining unclassified tables | Approve the proposal in the architecture document, section 5.8. | Some tenant-owned tables have a disposition that is recorded but not approved. | Every table has a recorded disposition in `app/governance/table_inventory.py`. Nothing is exported or deleted that the inventory does not cover. | Product and legal |
| D11 | Encryption at rest for stored documents and privacy artifacts | A managed data key from the platform key service, with envelope encryption and key rotation. | Documents and privacy artifacts are stored without encryption at rest. | Not met. Documents use private local storage without encryption. No key is configured or assumed. | Infrastructure and security |
| D13 | Ownership of import source files | Treat them as organization-owned documents, removed with their batch after retention. | Import sources are neither exported nor deleted by the privacy path. | Not exported and not deleted. | Product |

## Other open decisions and external dependencies

| Item | Question | Recommended option | Impact | Current state | Required owner |
|---|---|---|---|---|---|
| AI and channel entitlement feature keys | Which SIBVO plan feature keys gate AI and channel capabilities? | Use the keys SIBVO publishes in its entitlement catalogue. Do not add keys locally. | Capabilities fail closed (`entitlement_not_defined`) until keys are set. | No AI or channel plan feature key is defined in SIBVO. Dealsflo does not invent one. | SIBVO product owner (DFR1-005) |
| Channel execution permissions and role assignments | Which permission key allows a user to send through a channel, and which roles hold it? | A dedicated `governance.channels.send` key, granted to no role until approved. | No channel send can execute. The gate refuses all sends. | The default key `ai.execute` is not in the permission catalogue. No role can hold it. Decision recorded in the evidence document, section 6.2. | Product and security |
| Provider credentials and verification | Which real provider accounts are approved for verification, and who owns their credentials? | Verify each provider in a controlled environment with a dedicated credential, then enable it by configuration. | No provider is live. Readiness reports `not_verified`. | Verification runs only against a mocked HTTP boundary in tests. No live credential is stored. `PROVIDER_LIVE_ADAPTERS_ENABLED` is off. | Infrastructure and security |
| SIBVO usage-ingestion contract | Does SIBVO accept usage events, and what is the endpoint, schema and authentication? | Approve the contract in the SIBVO repository, then implement the reconciliation endpoint. | DFR1-053 stays Blocked. Dealsflo cannot reconcile usage with billing. | Inspected on SIBVO develop `20df0ef`: no usage-ingestion or reconciliation endpoint exists. SIBVO develop has since moved to `8505ba1`. Its only reconciliation job, `app/jobs/reconcile_product_access.py`, covers organizations, products, access and seats. It has no usage handling, so it does not satisfy this item. The contract is Proposed. | SIBVO platform owner and billing owner (DFR1-053) |

## Story status (after the merge of PR #148 at `2ca1350`)

| Story | Status | Open items |
|---|---|---|
| DFR1-006 | Partial | DFR1-002 and DFR1-005 external. Channel send permission (decision). Live provider verification (external). No AI executor exists yet. |
| DFR1-017 | Partial | No AI producer (DFR1-015). SIBVO reconciliation (DFR1-053). Scheduled maintenance (D7). |
| DFR1-050 | Partial | D1, D4, D7, D8, D9, D11, D13. Encryption at rest (D11). Audit deletion path (D8). |
| DFR1-053 | Blocked | Approved SIBVO usage contract and reconciliation endpoint. |

## Items that cannot start without a decision

- Document encryption at rest (D11): the key service and its owner must be chosen before envelope encryption is built.
- A `DELETE` block on `audit_events` (D8): needs the controlled deletion path and a foreign-key design that does not
  update audit rows.
- Retention enforcement for categories other than documents and invitations (D4).
- Maintenance scheduling in the deployment environment (D7).
