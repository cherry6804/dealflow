# Release 1 completion tracker

Authoritative source: `Dealsflo_Release1_Jira_Backlog_v2.xlsx` (58 stories, 15 epics). Story IDs, priorities,
dependencies and acceptance criteria are unchanged.

Status vocabulary (only these five are used):

1. Complete and verified
2. Implemented, verification pending
3. Blocked by external dependency
4. Awaiting product/legal approval
5. Not implemented

**No story and no epic is marked Complete.** The branch is `feature/DFR1-E13-ai-governance-consent-security-usage`,
and the latest checkpoint is recorded in each row where code exists. "Not audited" means the code was not inspected in
the session that produced this tracker, so the status is not claimed either way.

## Gate

E02 and every later epic wait for E13. E13 is open because DFR1-006, DFR1-017 and DFR1-050 are partial and DFR1-053 is
awaiting approval of the SIBVO usage contract (E12). The product owner set this order.

Open decisions for E13 are recorded, with options and recommendations that are not approved, in
`docs/architecture/e13-decision-readiness.md`. Evidence is in `docs/architecture/e13-completion-evidence.md`, section 14.

## Story tracker

| Story | Epic | Title | Priority | Status | Backend | Frontend | Evidence / commit | Remaining blockers |
|---|---|---|---|---|---|---|---|---|
| DFR1-001 | E01 | Baseline both repositories and preserve current work | P0 | 2 | Repository baseline recorded; work preserved on branch | n/a | Branch history; `docs/governance/s00-engineering-foundation-completion.md` | Verification of the baseline on a clean clone not performed |
| DFR1-002 | E01 | Approve target architecture and ADR register | P0 | 4 | ADR-0029 accepted; ADR-0025, 0026, 0027 still Proposed | n/a | `docs/adr/` | Approval of the three Proposed ADRs |
| DFR1-003 | E01 | Define Release 1 environment and provider dependency matrix | P0 | 4 | Matrix document exists. Owner, sandbox/prod status, approval and blocker dates are not recorded | n/a | `docs/product/release-1/E01-environment-and-provider-matrix.md` | Owners and blocker dates per dependency (product input) |
| DFR1-004 | E12 | Verify SIBVO identity and organization contract | P0 | 2 | SSO, organization binding and introspection implemented in E12 work | Login and SSO flows exist | Earlier E12 commits; `docs/architecture/sibvo-dealsflo-entitlement-contract.md` | Live contract verification against SIBVO not performed in this session |
| DFR1-005 | E12 | Verify subscription, entitlement and seat enforcement contract | P0 | 4 | Entitlement enforcement implemented (`workflow_automation` only) | Entitlement-aware UI partial | `app/governance/entitlement.py`; WP-A1 merged to SIBVO develop (merge 8505ba1) | SIBVO feature keys for AI and channels are unconfirmed; backlog still shows To Do |
| DFR1-006 | E13 | Define disabled-by-default capability policy | P0 | 2 | Central execution gate; fail-closed policy; audited decisions; per-action revalidation. Latest: `8012a22` | Capability settings UI | `app/governance/execution_gate.py`, `policy.py`; `8012a22` | Implemented and tested: provider gate, consent, channel policy (window, quiet hours, do-not-disturb), approval lifecycle, budget reservation. Provider health: stale connections are audited once per verification episode, and the policy denial names the readiness state (`app/providers/health.py`, `readiness.py`; 15 tests; evidence section 10). Not Done: DFR1-002 and DFR1-005 open (external); live provider verification not performed (external); no capability requires approval yet. See `e13-completion-evidence.md` |
| DFR1-007 | E04 | Confirm communication providers and channel capability matrix | P0 | 4 | None | None | None | Product choice of WhatsApp, Meta, email and telephony providers, then verification against official docs or accounts |
| DFR1-008 | E02 | Audit and close critical CRM vertical-slice gaps | P0 | 2 | Leads, contacts, customer profiles, requirements, deals, follow-ups, site visits, referrals APIs exist | CRM pages exist | Earlier CRM work | Formal gap audit not done |
| DFR1-009 | E03 | Implement channel identity and contact resolution | P0 | 5 | None | None | None | Depends on DFR1-008 audit and channels |
| DFR1-010 | E03 | Implement conversation, participant and message timeline | P0 | 5 | None | None | None | Depends on DFR1-009 |
| DFR1-011 | E04 | Build integration connection registry and secrets boundary | P0 | 5 | Connection registry and secret-reference boundary built (`app/governance/provider_connections.py`, migration `m4d9f3a6c2e8`); no provider probe registered, so nothing is verified | Provider adapters | `backend/tests/test_provider_connections.py` | Depends on DFR1-007 |
| DFR1-012 | E04 | Build verified webhook ingress and normalized event envelope | P0 | 5 | Webhook verification exists only for SIBVO billing | None | Billing webhook reliability (SIBVO) | Depends on DFR1-011 |
| DFR1-013 | E01 | Implement transactional outbox and background execution foundation | P0 | 2 | Outbox service, worker, handler registry; tests: rollback discards event, idempotent keys, bounded backoff, dead-letter, lease expiry, worker CLI | Not applicable | `app/outbox/`; `app/governance/alert_delivery.py` | Handler timeouts not enforced (lease expiry only). Worker deployment not defined |
| DFR1-014 | E04 | Implement outbound communication adapter contract | P0 | 5 | SMTP email delivery for authentication mail only | None | `app/auth/email_delivery.py` | Adapter contract not defined for channels |
| DFR1-015 | E06 | Build provider-independent AI gateway | P0 | 5 | None | None | None | Provider credentials (external) and product decision on first provider |
| DFR1-016 | E06 | Implement tenant-scoped knowledge ingestion and retrieval | P1 | 5 | None | None | None | Depends on DFR1-015 |
| DFR1-017 | E13 | Implement AI usage ledger and organization budgets | P0 | 2 | Ledger, reservations, expiry, thresholds, breakdowns, gate integration. Latest: `a869438` | Usage panel with breakdown | `app/governance/usage_ledger.py`; `a869438` | Implemented and tested: ledger, reservations, idempotency, budgets, 70/85 thresholds, in-app alerts, audited usage reversals (requested row committed before the budget changes, linked completed row, system actor when no user, duplicate reversal writes nothing; 7 tests). Not Done: no AI producer (DFR1-015); SIBVO usage reconciliation not built (DFR1-053); maintenance jobs not scheduled (D7). See `e13-completion-evidence.md` |
| DFR1-018 | E07 | Implement typed AI tool registry and authorization | P0 | 5 | None | None | None | Depends on DFR1-015 |
| DFR1-019 | E07 | Implement agent definitions, versioning and execution runtime | P0 | 5 | None | None | None | Depends on DFR1-018 and DFR1-017 |
| DFR1-020 | E09 | Implement explainable lead qualification and priority scoring | P0 | 5 | None | None | None | Depends on DFR1-008 and DFR1-015 |
| DFR1-021 | E07 | Deliver core lead intake and qualification agents | P0 | 5 | None | None | None | Depends on DFR1-019 and DFR1-020 |
| DFR1-022 | E09 | Deliver property matching and next-best-action recommendations | P0 | 2 | Requirement match run tables exist from earlier CRM work; next-best-action not built | None | Earlier CRM work | Matching and recommendation not audited; NBA not built |
| DFR1-023 | E08 | Implement workflow definition schema and version lifecycle | P0 | 5 | None | None | None | Depends on DFR1-013 and DFR1-019 |
| DFR1-024 | E08 | Implement workflow runtime and event trigger engine | P0 | 5 | Deal-created automation exists as a narrow precursor | Automation rules page exists | `app/automation_rules/` | Depends on DFR1-023 |
| DFR1-025 | E08 | Implement approval, human task and escalation nodes | P0 | 5 | None | None | None | Depends on DFR1-023 and DFR1-006 (approval model) |
| DFR1-026 | E08 | Build visual workflow editor and template catalogue | P0 | 5 | None | None | None | Depends on DFR1-023 |
| DFR1-027 | E05 | Implement voice provider adapter and inbound call lifecycle | P0 | 3 | None | None | None | Telephony provider account (external); depends on DFR1-007, DFR1-011, DFR1-015 |
| DFR1-028 | E05 | Implement voice conversation, transcription and post-call CRM update | P0 | 3 | None | None | None | Telephony and transcription providers (external); depends on DFR1-027 |
| DFR1-029 | E04 | Connect WhatsApp Business and validate inbound/outbound | P0 | 3 | None | None | None | Meta Business account and WhatsApp approval (external) |
| DFR1-030 | E04 | Connect Meta Messenger and Instagram messaging | P1 | 3 | None | None | None | Meta app review (external) |
| DFR1-031 | E04 | Connect email inbound/outbound and thread mapping | P0 | 5 | Outbound SMTP for authentication mail only; no inbound | None | None | Mail provider credentials (external) for inbound |
| DFR1-032 | E07 | Deliver assignment, follow-up and site-visit agents | P0 | 5 | None | None | None | Depends on DFR1-019, DFR1-022, DFR1-025 |
| DFR1-033 | E10 | Deliver Dealsflo Copilot with authorized business queries | P1 | 5 | None | None | None | Depends on DFR1-015 and DFR1-018 |
| DFR1-034 | E10 | Deliver generative property and communication content studio | P1 | 5 | None | None | None | Depends on DFR1-015 and DFR1-017 |
| DFR1-035 | E10 | Deliver document and multimodal extraction MVP | P1 | 5 | Document storage exists; extraction not built | Document upload exists | `app/documents/` | Depends on DFR1-015 and DFR1-016 |
| DFR1-036 | E11 | Build organization AI and automation settings | P0 | 2 | Capability switches, master and child, audited; defaults disabled | Settings UI exists | `app/governance/service.py`; governance API | Connection, consent, activation and budget requirements not yet enforceable |
| DFR1-037 | E11 | Build no-code agent configuration studio | P1 | 5 | None | None | None | Depends on DFR1-019 and DFR1-036 |
| DFR1-038 | E11 | Build integration configuration and health UI | P1 | 5 | None | None | None | Depends on DFR1-011 and DFR1-012 |
| DFR1-039 | E09 | Deliver deal risk, pipeline and revenue baseline forecasts | P1 | 5 | None | None | None | Depends on DFR1-020 and DFR1-022 |
| DFR1-040 | E14 | Build AI and automation command center overview | P1 | 5 | None | None | None | Depends on DFR1-017, DFR1-019, DFR1-024, DFR1-036 |
| DFR1-041 | E15 | Run full end-to-end real-estate lead-to-visit scenario | P0 | 5 | None | None | None | Depends on channels, agents, workflow runtime |
| DFR1-042 | E15 | Run tenant isolation, authorization and abuse tests | P0 | 2 | Tenant isolation and authorization test suites exist (1482 backend tests) | None | Full backend suite on each checkpoint | Abuse and rate-limit tests not built; depends on DFR1-036, DFR1-041 |
| DFR1-043 | E15 | Prepare 15-day candidate and 30-day stabilization backlog | P0 | 5 | None | None | None | Depends on DFR1-041 and DFR1-042 |
| DFR1-044 | E05 | Deliver outbound voice campaigns with policy controls | P0 | 3 | None | None | None | Telephony provider (external); depends on DFR1-027, DFR1-028, DFR1-036 |
| DFR1-045 | E09 | Add prediction feedback and model evaluation pipeline | P1 | 5 | None | None | None | Depends on DFR1-020 and DFR1-039 |
| DFR1-046 | E10 | Add video understanding and richer floor-plan extraction | P2 | 5 | None | None | None | Depends on DFR1-035 |
| DFR1-047 | E11 | Add custom business profile and pipeline builder | P1 | 5 | None | None | None | Depends on DFR1-008 and DFR1-036 |
| DFR1-048 | E11 | Add custom scoring and recommendation policy builder | P1 | 5 | None | None | None | Depends on DFR1-020, DFR1-022, DFR1-047 |
| DFR1-049 | E14 | Add channel, agent, workflow and revenue analytics | P1 | 5 | None | None | None | Depends on DFR1-040 and DFR1-041 |
| DFR1-050 | E13 | Complete retention, export, deletion and privacy controls | P0 | 2 | Export (ZIP, not-covered notices, CRM sub-records), deletion (documents, invitations, contacts with deferral), retention, verification, audit. Latest: `964da40` | Privacy UI shows requests and outcomes | `app/governance/privacy_execution.py`; `964da40` | Implemented and tested: table-level inventory enforced for all 69 tables, log tracebacks withheld, legal holds, retention for documents and invitations. Not Done: decisions D1, D4, D7, D8, D9, D11, D13 open; encryption at rest not met (D11); audit immutability not verified (D8); scheduler not deployed (D7). See `e13-completion-evidence.md` |
| DFR1-051 | E15 | Performance, concurrency and resilience validation | P0 | 5 | Concurrency tests exist for ledger and seats only | None | Usage and seat concurrency tests | Full load and resilience validation not built; depends on DFR1-024, DFR1-029, DFR1-041 |
| DFR1-052 | E15 | Production deployment, monitoring, backup and rollback | P0 | 5 | No deployment configuration in this branch | None | `infrastructure/` contains a README only | Depends on DFR1-043 and DFR1-051 |
| DFR1-053 | E12 | Complete SIBVO usage reconciliation and entitlement lifecycle tests | P0 | 4 | Entitlement lifecycle tests exist from E12; WP-E13-next adds downgrade lifecycle tests (6) and billing audit endpoint tests (6) on `feature/DFR1-E13-DFR1-053-lifecycle-tests`; reconciliation not built; SIBVO inspection (develop `20df0ef`) found no usage ingestion or reconciliation endpoint; no Dealsflo webhook ingestion or replay endpoint exists | None | E12 tests; WP-A1 SIBVO billing reliability; `e13-completion-evidence.md` sections 8 and 12 | Approval of the SIBVO usage contract (not approved; status Blocked). Usage summaries and reconciled usage stay unmet. |
| DFR1-054 | E04 | Add channel provider resilience and reconciliation | P1 | 5 | None | None | None | Depends on channel stories |
| DFR1-055 | E07 | Add agent evaluation, safety regression and marketplace catalogue | P1 | 5 | None | None | None | Depends on DFR1-019, DFR1-021, DFR1-032 |
| DFR1-056 | E08 | Add workflow simulation, replay and advanced debugging | P1 | 5 | None | None | None | Depends on DFR1-024 and DFR1-026 |
| DFR1-057 | E10 | Add multilingual regional conversation and content quality suite | P1 | 5 | None | None | None | Depends on DFR1-028 and DFR1-034 |
| DFR1-058 | E15 | Complete customer pilot, defect triage and release sign-off | P0 | 3 | None | None | None | Pilot with real customers and release-owner approval (external); depends on DFR1-049, DFR1-050, DFR1-052, DFR1-053 |

## Epic summary

No epic is Done.

| Epic | Stories | Complete and verified | Verification pending | Blocked | Awaiting approval | Not implemented |
|---|---|---|---|---|---|---|
| E01 Foundation | 4 | 0 | 2 (001, 013) | 0 | 2 (002, 003) | 0 |
| E02 CRM Core | 1 | 0 | 1 (008) | 0 | 0 | 0 |
| E03 Identity and inbox | 2 | 0 | 0 | 0 | 0 | 2 |
| E04 Communication gateway | 8 | 0 | 0 | 2 (029, 030) | 1 (007) | 5 |
| E05 Voice AI | 3 | 0 | 0 | 3 (027, 028, 044) | 0 | 0 |
| E06 AI platform | 2 | 0 | 0 | 0 | 0 | 2 |
| E07 AI workforce | 5 | 0 | 0 | 0 | 0 | 5 |
| E08 Automation | 5 | 0 | 0 | 0 | 0 | 5 |
| E09 Predictive intelligence | 4 | 0 | 1 (022) | 0 | 0 | 3 |
| E10 Generative and multimodal | 5 | 0 | 0 | 0 | 0 | 5 |
| E11 Studios | 5 | 0 | 1 (036) | 0 | 0 | 4 |
| E12 SIBVO integration | 3 | 0 | 1 (004) | 0 | 2 (005, 053) | 0 |
| E13 AI governance | 3 | 0 | 3 (006, 017, 050) | 0 | 0 | 0 |
| E14 Command center | 2 | 0 | 0 | 0 | 0 | 2 |
| E15 Quality and release | 6 | 0 | 1 (042) | 1 (058) | 0 | 4 |

Counts sum to the 58 stories above (verified by script). DFR1-002 and DFR1-005 are awaiting approval.

## Remaining external activation requirements

- Meta Business and WhatsApp approval, Meta app review (DFR1-029, 030).
- Telephony and transcription provider accounts (DFR1-027, 028, 044).
- Provider credentials for the AI gateway and the first model provider (DFR1-015).
- Mail provider credentials for inbound email (DFR1-031).
- SIBVO usage contract approval (DFR1-053) and confirmed SIBVO feature keys for AI and channels (DFR1-005).
- Scheduler, worker and deployment ownership for outbox, privacy and usage maintenance (DFR1-013, 050, 052).
- Real customer pilot and release-owner approval (DFR1-058).
