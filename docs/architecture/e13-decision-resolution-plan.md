# E13 decision identifier resolution and decision-resolution plan

Status: **documentation only. No decision is approved, renamed or reinterpreted by this file.** It records what each
identifier means in each source, names what must be ruled on, and sets out the order in which the owners should decide.

Merge state checked: PR #151 is merged into `develop` as `137a3d1`. Commit `e0d558b` (the decision-readiness documentation)
is an ancestor of `137a3d1`. The merge changed three files, all under `docs/`. The decision-readiness file contains 20
decision entries and the dependency, implementation-impact, traceability and sequence matrices (Parts A to F).

---

## 1. The D1 and D9 identifier ambiguity

The same identifiers mean different things in different sources. Each definition below is quoted from its source.

### 1.1 Competing definitions

| Identifier | Source | Definition as written | Owner recorded in source |
|---|---|---|---|
| D1 | `e13-decision-register.md` (decision register) | "Clear free-text fields on deletion, or delete rows?" Recommended option: "Clear only approved personal free-text fields. Scope in the architecture document, section 5.9." | Product and legal |
| D1 | `e13-completion-evidence.md`, section 3 | "Clear free-text fields on deletion, or delete rows?" | Product and legal |
| D1 | `e13-decision-readiness.md` (as merged in PR #151) | "Data classification and ownership." Maps to the register's D9. | Product and legal |
| D9 | `e13-decision-register.md` | "Classification of remaining unclassified tables." Recommended option: "Approve the proposal in the architecture document, section 5.8." | Product and legal |
| D9 | `e13-completion-evidence.md`, section 3 | "Classification of remaining unclassified tables." | Product and legal |
| D9 | `e13-decision-readiness.md` (as merged in PR #151) | "Export and deletion policy." Maps to the register's D1 (free-text clearing) and export scope. | Product and legal |

The architecture document itself uses the register's meaning: section 5.8 is "Classification proposal for the 27
unclassified tables (for review, not authorization)", and section 5.9 is "Free-text field inventory for decision D1
(for approval; nothing is cleared yet)".

### 1.2 The conflict in one line

The register and the architecture document say **D1 = free-text clearing** and **D9 = classification**. The decision-readiness
file, which PR #151 merged, says **D1 = classification** and **D9 = export and deletion**, with a mapping table. Both cannot
stand in the same release record. Until the owner rules, a reference to D1 or D9 is ambiguous and must name its source.

### 1.3 Ruling required

The release owner must choose one of these, and record it here:

- **Option R1 (keep the register's meanings).** D1 = free-text clearing; D9 = classification. The decision-readiness
  file's labels are corrected to match. Lowest churn: the register, evidence section 3 and the architecture document already
  agree.
- **Option R2 (adopt the decision-readiness labels).** D1 = classification; D9 = export and deletion. The register, evidence
  section 3 and the architecture document are corrected. Higher churn; three documents change.
- **Option R3 (scope-qualified identifiers, no renumbering).** Keep both sets of meanings, but cite them as
  `E13-D1 (register)` and `E13-D1 (readiness)`, and state which one a decision record uses. Lowest risk; leaves two labels in
  circulation until retired.

**Recommendation (not a decision):** Option R1. It matches the older documents, which the rest of the E13 record already cites.
Option R3 is the fallback if the owner wants to keep the readiness file's labels.

**Owner:** Product and legal, as recorded in each source. The repository does not record a named individual. The release
owner must name the person who makes this ruling.

---

## 2. Other identifier collisions (D-numbers reused across documents)

The collision is not limited to D1 and D9. ADR-0032 uses `D1` to `D8` for provider decisions. The E13 register uses several of
the same numbers for different questions.

| Identifier | ADR-0032 meaning (decided) | E13 register meaning (open) | Architecture document meaning | Collision |
|---|---|---|---|---|
| D1 | First LLM adapter is OpenAI | Free-text clearing or classification (see section 1) | Free-text inventory (section 5.9) | Yes |
| D2 | Database-backed provider catalogue rejected for now | Not used | Not checked | Not in E13 |
| D4 | Credential storage reused; no duplicate credentials | Retention period per category | Retention (section 5) | Yes |
| D5 | Verification runs in the worker | Not used | Not checked | Not in E13 |
| D6 | Live adapter flag never enabled in CI | Not used | Not checked | Not in E13 |
| D7 | Verification attempt history kept | Scheduler for maintenance jobs | Not checked | Yes |
| D8 | Honest status ("Not verified") | Audit immutability and deletion | Not checked | Yes |
| D11 | Not used | Encryption at rest for documents | Not checked | Not in ADR-0032 |
| D12 | Not used | Not in the register | Legal holds: "holds block deletion, not export. Met as decided." | Defined only in the architecture document |
| D13 | Not used | Import source files | Not checked | Not in ADR-0032 |

"Not checked" means this pass did not classify the occurrence. A raw search for each identifier returns hits in other
documents, but many are unrelated text, so no count is stated here.

### 2.1 Consequence

A reader who sees "D7" in ADR-0032 and "D7" in the E13 register will find two different questions. Evidence and tracker entries
that cite a bare number are ambiguous. The fix is to cite the source with the number (for example, "ADR-0032 D7" or
"E13 register D7"), without renaming either set.

### 2.2 Ruling required

- **Option N1 (source-qualified citations).** Every reference names its document. No renumbering. Owner: E13 release owner.
- **Option N2 (renumber the E13 register with a prefix, such as `E13-D7`).** Changes the register, evidence section 3,
  the decision-readiness file and the tracker. Owner: E13 release owner, with the ADR-0032 author informed.

**Recommendation (not a decision):** Option N1 now, and Option N2 only if the E13 decisions grow beyond this list.

---

## 3. Owners

The repository records roles, not people. The roles below are copied from the sources. **No individual is named here,
because none is recorded in the repository.** The release owner must assign a named person to each role before any
decision can be recorded as approved.

| Role (as written in sources) | Decisions and questions |
|---|---|
| Product and legal | D1 or D9 (see section 1), D4, D13 |
| Infrastructure | D7, D11, provider credentials and verification |
| Security and legal | D8 |
| Security | AI actor permission key, channel send keys, role granting |
| Product | AI actor key and role matrix, channel keys (with security), D13 (import retention) |
| SIBVO product owner | AI capability entitlement keys (DFR1-005) |
| SIBVO platform owner and billing owner | Usage-ingestion contract, event schema, idempotency, reversal, retry and replay, identity mapping, billing webhook ownership |
| E13 release owner | Choice of identifier scheme (sections 1 and 2) and the release sign-off |

---

## 4. Prioritized decision-resolution plan

### 4.1 Decisions requiring product, security or architecture approval

These are open questions with no approved answer. Each needs a recorded approval before work that depends on it can start.

| Priority | Decision | Approval authority | Evidence required to approve |
|---|---|---|---|
| 1 | Identifier ruling (sections 1 and 2) | E13 release owner | A dated note in this file naming the option chosen |
| 2 | AI actor permission key and role grants | Security and product | A key name, the roles that receive it, the owner-only status, and the catalogue change approved |
| 3 | AI capability entitlement keys (keep `ai_gateway` or split) | SIBVO product owner | The SIBVO catalogue decision, with the snapshot change if any |
| 4 | Usage-ingestion contract (umbrella), split into 053a and 053b | SIBVO platform and billing owners | Contract section 7 status changed from Proposed to Approved, with the SIBVO endpoint named |
| 5 | Event schema and versioning | SIBVO platform owner with Dealsflo | Approved schema with its version rule |
| 6 | Idempotency and deduplication key | SIBVO platform owner | Approved key definition and conflict rule |
| 7 | Usage reversal and correction | SIBVO billing owner with Dealsflo | Approved reference rule for reversals |
| 8 | Billing webhook ownership | SIBVO platform owner and product owner | A written ownership statement; Option A recommended in the readiness file |
| 9 | Channel send permission and entitlement keys | Security and product, after ADR-0028 is accepted | ADR-0028 status Accepted; the key approved |
| 10 | D4 retention periods per category | Product and legal | A period and legal basis recorded for each category |
| 11 | D7 scheduler for maintenance jobs | Infrastructure | A named environment, the schedule, and the alerting owner |
| 12 | D8 audit immutability and deletion path | Security and legal | A decision on `DELETE` handling and the controlled path, if any |
| 13 | D11 encryption at rest and key management | Infrastructure and security | The key service chosen and the custody owner |
| 14 | D13 import attachment retention | Product | A retention rule, after D4 is decided |
| 15 | Role-granting authority beyond owner | Security and product | A decision on delegation, if any |

### 4.2 Decisions that block implementation

Work that depends on these cannot start, or cannot be verified end to end, until they are decided.

| Blocked work | Blocked by | Story affected |
|---|---|---|
| Any AI execution end to end | Items 2 and 3 in 4.1 | DFR1-006, DFR1-015 (other epic) |
| DFR1-053a, Dealsflo usage producer | Items 4 to 6 in 4.1, and DFR1-017 | DFR1-053 |
| DFR1-053b, SIBVO ingestion and reconciliation | Items 4 to 7 in 4.1 | DFR1-053 (SIBVO repository) |
| Channel sending | Item 9 in 4.1 and ADR-0028 | DFR1-006 channel gate; communication epics |
| Deletion and export for the remaining categories | Item 1 (identifier ruling) and the D1 or D9 ruling | DFR1-050 |
| Retention enforcement for categories other than documents and invitations | Item 10 in 4.1 | DFR1-050 |

### 4.3 Decisions that can safely wait

These do not block a backlog criterion today, or their current behaviour is safe and tested. Each is disclosed as a limitation.

| Decision | Current safe behaviour | Disclosure required |
|---|---|---|
| D7 scheduler (item 11) | Maintenance code paths are tested; jobs run where the worker runs | Maintenance is not scheduled in any deployed environment |
| D8 deletion path (item 12) | `UPDATE` is blocked; `DELETE` is allowed and recorded as a gap | Audit rows can be deleted directly |
| D11 encryption (item 13) | Provider credentials are encrypted; documents are not | Documents are not encrypted at rest |
| D13 import retention (item 14) | Import files are kept with their batch; not exported | Gap for data-subject requests that cover imports |
| Role delegation (item 15) | Owner-only administration | Customers share the owner role |
| Fail-closed grace period | No grace period; deny when no valid snapshot | None needed unless a business need appears |

### 4.4 Evidence or approval required to unblock each story

| Story | Current status | Evidence or approval that unblocks each open part |
|---|---|---|
| DFR1-006 | Partial | (a) Approved AI actor key and role grants, with a catalogue test (item 2). (b) SIBVO-confirmed AI entitlement keys (item 3). (c) ADR-0028 Accepted, and the channel keys approved (item 9). (d) DFR1-002: ADR-0025, 0026 and 0027 approved, as listed in the decision register, section 4. (e) An AI executor, which belongs to DFR1-015 (another epic). Status changes only when (a) to (e) are evidenced. |
| DFR1-017 | Partial | (a) A usage producer, which belongs to DFR1-015 (another epic). (b) Maintenance running in a deployed environment (item 11), with run evidence. |
| DFR1-050 | Partial | (a) The identifier ruling (item 1) and the D1 or D9 ruling, with approved scope for each category. (b) Retention periods with legal basis (item 10), and executors for each category that gains a period. (c) Communication tables for messages, calls and transcripts, which belong to E03 and E04. (d) Retention job run evidence (item 11). |
| DFR1-053 | Blocked | (a) SIBVO usage contract approved and its status changed from Proposed (items 4 to 8). (b) SIBVO ingestion endpoint built and tested in the SIBVO repository. (c) Dealsflo producer (053a) after DFR1-017. (d) Reconciliation evidence from SIBVO showing no unexplained mismatch. (e) Billing webhook ownership recorded (item 8), if replay through an endpoint is wanted. |

### 4.5 Recommended next action

1. The E13 release owner names a person for each role in section 3, and rules on the identifier scheme (items 1 in 4.1 and
   sections 1 and 2). This is documentation only and needs no code.
2. Product and security decide the AI actor permission key (item 2). This unblocks the largest number of DFR1-006 criteria
   without touching SIBVO.
3. The SIBVO platform and billing owners review the usage contract (items 4 to 8). This is the only route to DFR1-053.

---

## 5. What this file does not change

- No story status changes. DFR1-006, DFR1-017, DFR1-050 remain Partial. DFR1-053 remains Blocked. E13 is not Done.
- No decision is approved, renamed or reinterpreted here. Section 1 and section 2 record the conflicts, not a ruling.
- No application code, migration, permission, entitlement key, endpoint or configuration changes.
- E02 and E06 are untouched.
