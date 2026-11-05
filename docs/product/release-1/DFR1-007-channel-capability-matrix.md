# DFR1-007 Channel provider comparison, decisions and capability matrix

- **Story:** DFR1-007, Confirm communication providers and channel capability matrix (Epic DFR1-E04, P0, 2 points, Sprint S1).
- **Status:** Documentation complete. **Provider strategy approved** as the Release 1 target architecture (ADR-0033, Accepted). **No provider account, credential, sandbox, API permission or live integration is verified.** Nothing here is a verified connection or a tested integration.
- **Research date:** 2026-11-05. Pages were fetched that day. Provider terms change; re-check before contracting.
- **Scope:** Documentation only. No application code, no provider account, no sandbox, no credentials.

## 0. Labels used in this document

- **Verified (official source):** stated on an official provider page fetched on 2026-11-05. Link given.
- **Reported (secondary):** from search snippets or third-party guides only. Confirm with the provider.
- **Assumption:** planning assumption. Confirm before relying on it.
- **Not verified:** not checked against a provider. Stays this way until the provider confirms in writing or a test passes.

Three states are kept separate throughout:

| State | Meaning | Current status |
|---|---|---|
| **Selected provider** | The architecture names it (ADR-0033). | Yes, for each channel below. |
| **Verified connection** | A real account and credential passed the provider's verification probe in an environment. | **None exists.** |
| **Tested integration** | Automated tests pass against the provider's sandbox or live API. | **None exists.** Existing tests use mocked boundaries only. |

## 1. Approved provider strategy (summary)

| Channel | Provider | Role | Launch status |
|---|---|---|---|
| India telephony | Exotel | Primary | Required for Release 1 inbound and outbound India calling |
| International telephony | Twilio | Primary, per supported country and calling direction | Required for each validated country and direction |
| WhatsApp | Meta WhatsApp Business Cloud API (direct) | Primary | Release 1; no BSP at launch |
| Messenger and Instagram | Official Meta APIs | Primary | Release 1 P1, not a launch blocker |
| Email | Amazon SES | Initial transport | Release 1, subject to inbound, threading and attachment validation |
| Call recording | Supported, off by default | Policy-gated | Enabled only under consent, privacy, retention and organisation policy |

## 2. Telephony: facts and evidence

### 2.1 Exotel (India primary)

| Criterion | Status | Evidence |
|---|---|---|
| Inbound call event | Verified: `incoming_call` posted to a configured URL with `call_sid`, `direction`, `from`, `to`, `exophone`, `timestamp`, `caller_info` | [Call notifications](https://developer.exotel.com/docs/ip-pstn-webrtc/api-reference/call-notifications) |
| Status callbacks | Verified: `outbound_call`, `call_ringing`, `call_answered`, `call_completed`, `missed_call` | Same |
| Webhook retry | Verified: non-200 retried at 5 s, 30 s and 5 min; dropped after three failures and logged | Same. Dropped events need reconciliation |
| Webhook authentication | **Not verified. Not documented on the page fetched.** Blocker for the Exotel adapter | Same (no signature, token or allowlist described) |
| Answer, bridge, transfer | Reported: call flows and connect APIs exist. Inbound answer, bridge and human transfer not verified | [Make a call API](https://developer.exotel.com/api/make-a-call-api) |
| AI streaming | Not verified. To be confirmed in writing (protocol and direction) | — |
| Number types and India availability | Reported: ExoPhone (virtual) and toll-free; monthly rental per number | [Number types FAQ](https://developer.exotel.com/docs/faqs/number-types) |
| Sandbox and test number | Not verified. Not documented on the pages fetched | — |
| Pricing | Not published for inbound. Third-party figures conflict (₹0.30–0.50 vs ₹0.80–1.00 per minute). **Written quotation required.** | [Exotel migration blog](https://exotel.com/blog/migrate-twilio-to-exotel-voice-ai-india/) (unverified), [CloudTalk guide](https://www.cloudtalk.io/blog/exotel-pricing/) (secondary) |
| Concurrency limits | Not verified | — |

### 2.2 Twilio (international primary)

| Criterion | Status | Evidence |
|---|---|---|
| Webhook signing | Verified: `X-Twilio-Signature`, HMAC-SHA1 over the URL and parameters with the auth token. JSON bodies covered by `bodySHA256`. SDK validation recommended | [Secure webhooks](https://www.twilio.com/docs/usage/webhooks/webhooks-security) |
| Replay protection | Not described by Twilio. Dealsflo must add its own window and deduplication | Same |
| India voice restrictions | Verified: outbound calls to India only from non-Indian numbers. Toll-free numbers in India are reachable from outside India and are not for outbound use. Voice OTP and 2FA not permitted | [India voice guidelines](https://www.twilio.com/en-us/guidelines/in/voice) |
| India SMS | Verified: domestic messages need DLT registration of the company and sender ID before Twilio registration | [India SMS guidelines](https://www.twilio.com/en-us/guidelines/in/sms) |
| Recording and consent | Verified: consent from the recipient is needed before commercial communications; TRAI may treat calls without consent as unsolicited commercial communication. Recording rules are not stated on the page | [India voice guidelines](https://www.twilio.com/en-us/guidelines/in/voice) |
| Per-country number availability | **Not verified for any target country.** Must be validated per country | — |
| Pricing | Not pulled in this pass. **Written quotation or current price list required.** | — |
| Sandbox | Assumed available (test credentials). Trial limits per country not verified | — |

### 2.3 Knowlarity (not selected)

- Developer reference did not load its content. Webhook authentication, sandbox and inbound payload not verified. Only a 2013 integration guide was readable ([secondary](https://www.scribd.com/document/202780359/Knowlarity-Sr-Integration-Guide-Jan-2013-2)).
- Not selected. Re-evaluate only if current documentation is supplied.

### 2.4 Telephony comparison (scores: 1 weak, 2 adequate, 3 strong, ? not verified)

| Dimension | Exotel | Twilio | Knowlarity |
|---|---|---|---|
| Inbound webhook shape | 3 (verified) | 3 (verified) | ? |
| Webhook authentication | ? (blocker) | 3 (verified) | ? |
| Retry and delivery | 3 (verified) | 2 | ? |
| India number availability | 3 (reported) | 1 (outbound restriction; per-country unverified) | ? |
| Sandbox access | ? | 2 (assumed) | ? |
| Pricing transparency | 1 | ? | ? |
| Security | ? until auth confirmed | 3 | ? |
| Reliability | 2 | 3 (assumed) | ? |
| Developer experience | 2 | 3 | 1 |
| Vendor dependency and portability | 2 | 2 | 2 |

## 3. Country-specific selection and capability routing

Routing key: **(number country, calling direction, capability)**. The router reads the organisation's configuration and the connection's verified status.

| Scenario | Provider | Rule |
|---|---|---|
| India calling, Indian number | Exotel | Primary. Outbound from Indian numbers through Exotel |
| International, country in the validated list | Twilio | Only for each country and direction that has been validated (section 6) |
| International, country not validated | None | Refused with a normalised reason. Handed to a human |
| Outbound to Indian numbers from Twilio | **Not allowed** | Twilio's India rule: outbound to India only from non-Indian numbers. Refused; route through Exotel |
| Toll-free outbound in India via Twilio | **Not allowed** | Refused |
| Any direction, provider not verified for the organisation | None | Refused. No silent fallback |
| Configured fallback provider | Only if the organisation has configured it | Explicit configuration, audited |

Rules:

- Routing never names a provider in CRM or workflow services. The routing layer maps the request to a configured adapter.
- A route is used only when the organisation has enabled the capability and the connection is verified and healthy (ADR-0032).
- Refusals are audited with the reason code. Nothing is placed or sent on a refused route.

## 4. WhatsApp Business (Meta Cloud API, direct)

| Criterion | Status | Evidence |
|---|---|---|
| Route | Direct Cloud API, no BSP at launch (approved) | ADR-0033 |
| Rate card | Verified: rates published in INR for India (billing localisation from 1 January 2026; migrate by 31 December 2026) | [WhatsApp pricing](https://developers.facebook.com/docs/whatsapp/pricing) |
| Free service messages | Verified: 1,000 free service messages per business phone number per month, from 1 October 2026 | Same |
| Per-message amounts | **Not in the page.** Third-party figures (marketing ₹0.8631, utility ₹0.115) are reported only. Use the official INR rate-card file | Reported |
| Prerequisites | Meta business verification, WABA, phone number, approved templates for business-initiated messages, messaging policies | Meta documentation to confirm for the account type |
| Webhook verification | To confirm from Meta's webhook documentation before implementation | — |
| Sandbox | To confirm (test number availability) | — |

## 5. Messenger and Instagram (Meta, P1)

| Criterion | Status | Evidence |
|---|---|---|
| Prerequisites | Verified: Meta app with Messenger use case, linked Facebook Page, Instagram Professional account for Instagram, Business Verification if non-role users will use it | [Messenger Platform overview](https://developers.facebook.com/docs/messenger-platform/overview) |
| Access levels | Verified: Standard Access for users with a role; Advanced Access needs App Review. App Review not needed to message your own Page only | Same |
| Permissions | Verified list: `pages_show_list`, `pages_manage_metadata`, `pages_messaging`, `pages_read_engagement`, `business_management`; Instagram adds `instagram_basic`, `instagram_manage_messages` | Same |
| Messaging window | Verified: 24 hours after a user message; up to 7 days after a Click-to-Messenger or Click-to-Direct ad | Same |
| Webhook signature | Expected `X-Hub-Signature-256`. **Not verified on the page.** Confirm in Meta's webhook documentation | — |
| Scope for Dealsflo | Dealsflo-owned Pages need no App Review. Customers' Pages need Advanced Access and App Review | Analysis |

## 6. Email (Amazon SES, initial transport)

| Criterion | Status | Evidence |
|---|---|---|
| Delivery outcomes | Verified: accepted requests return a message ID; bounce, complaint and auto-response notifications return to the sender by email or Amazon SNS; suppressed addresses are refused | [SES sending process](https://docs.aws.amazon.com/ses/latest/dg/send-email-concepts-process.html) |
| Identity verification | To confirm in the SES getting-started documentation (domain verification, DKIM) | — |
| Sandbox and production access | To confirm (sending limits and production access request) | — |
| Inbound receiving | **Required and not verified.** Confirm SES receiving rules, storage and routing for inbound messages | — |
| Threading and attachments | **Required and not verified.** Must be tested end to end before launch | — |
| Pricing | To confirm from SES pricing page | — |

## 7. Costs (pending written quotations)

Exact pricing is not available for most items. Each entry below is a planning assumption until replaced by a quotation or a current price list.

| Item | Current basis | Quotation needed from |
|---|---|---|
| Exotel India calls and numbers | Not published for inbound; third-party only | Exotel sales |
| Exotel SMS and WhatsApp (if used) | Not researched | Exotel sales |
| Twilio international voice, per country and direction | Not pulled | Twilio price list or sales, per country |
| Twilio number rental, per country | Not pulled | Twilio |
| WhatsApp messages (INR, per category) | Rate card file; Meta publishes India INR rates. Figures in third-party sources not used | Meta rate card file |
| BSP fees | Not applicable at launch (direct) | — |
| Messenger and Instagram messages | Meta messaging pricing not researched in this pass | Meta documentation |
| SES sending and receiving | Not pulled | AWS pricing page |
| Recording storage | Depends on retention (section 8) | Storage decision |

Cost attribution: every provider call is metered by organisation, provider, capability and direction in the shared usage ledger. No cost figure in this document is a commitment.

## 8. Call recording, consent, retention and access control

Recording is supported in Release 1 and **disabled by default**. It is enabled per organisation only when all of the following hold.

1. **Consent:** the organisation's configured consent policy permits recording for the call type, and the caller is informed before recording starts. The provider's consent requirement (Twilio: recipient consent for commercial communication, verified) is applied in addition to Dealsflo's policy.
2. **Policy:** privacy and retention settings for the organisation allow recording. A recording is not made when the policy is off, and the decision is audited.
3. **Retention:** each recording has a retention period set by policy. Expired recordings are deleted by a job that writes an audit record. Deletion is not complete until storage confirms it. (Retention periods are a product decision; no default is set here.)
4. **Access:** only members with a recording permission can play or download a recording. Access is server-side and audited. Links are short-lived and organisation-scoped.
5. **Transcription:** not done unless recording is enabled and the consent policy also permits transcription. Transcripts follow the same retention and access rules.
6. **Storage location:** must be confirmed against data residency requirements for India. Not decided here.
7. **Provider-side recording:** if a provider records by default, Dealsflo disables it when the policy is off and verifies the setting. Not verified for any provider.

Open questions for the owner: retention period by call type; storage location; whether recordings are needed for the Release 1 pilot.

## 9. Security and compliance

- **Webhooks:** verified ingress is DFR1-012 (HMAC over timestamp and body, constant-time comparison, replay window, deduplication). Provider-specific signing (for example Twilio `X-Twilio-Signature`) is implemented by the provider adapter, using DFR1-012's contract. Exotel signing is unknown.
- **Secrets:** all provider credentials go through the DFR1-011 connection registry and secrets boundary (encrypted, shown once, never in configuration files or logs). Each provider's secret types are listed in its adapter specification.
- **TRAI and DLT:** commercial SMS and calls to Indian numbers are regulated. Sender registration, consent records and legal review are required before launch. Confirm with counsel.
- **Data protection:** personal data in provider payloads is redacted before storage (DFR1-012 redaction). Audit records hold identifiers and reason codes, not payloads.
- **Provider data-use terms:** not reviewed in this pass for any provider. Required before live use.

## 10. Verification and sandbox prerequisites (per provider)

| Provider | Required before implementation | Required before live use |
|---|---|---|
| Exotel | Written webhook authentication; sandbox account and test number; inbound calling API; answer and bridge; human transfer; AI streaming protocol; number and regulatory requirements; pricing and concurrency limits | Account approval; live numbers; regulatory registrations; signed contract |
| Twilio | Per-country and per-direction validation (number availability, regulatory bundle, rules); test credentials | Production account; per-country numbers; regulatory approvals; contract |
| WhatsApp (Meta Cloud API) | Business verification; WABA; test number; template approvals; webhook verification confirmed | App review (if required by permissions); production number; policy compliance; approved templates |
| Messenger and Instagram | Meta app; Page and Instagram account; permissions; webhook verification confirmed | App Review for Advanced Access (for customer Pages); business verification |
| Amazon SES | Sender and domain identity verified (DKIM); sandbox testing; inbound receiving rule; threading and attachment tests | Production access request; bounce and complaint handling live |

No account, credential or sandbox exists in this repository for any of these. Nothing was created.

## 11. Impact on DFR1-011 and the implementation sequence

Approved sequence (one story and one PR at a time; each waits for the previous PR to merge):

1. **DFR1-011:** telephony and channel-specific connection verification. Adds provider keys and probes. Probes run only against real connections in a configured environment; they never mark a connection verified without a real check.
2. **DFR1-027:** Exotel inbound call lifecycle. Blocked until the Exotel verification gate in section 10 is met.
3. **DFR1-028:** voice conversation, transcription and post-call CRM update.
4. **DFR1-029:** WhatsApp Cloud API.
5. **DFR1-031:** Amazon SES email integration.
6. **DFR1-030:** Messenger and Instagram integration.
- Twilio is implemented as a separate adapter after the Exotel adapter contract is established and tested.

## 12. Unresolved questions

1. Exotel: webhook authentication method; sandbox; AI streaming protocol; written pricing and concurrency.
2. Twilio: number availability and rules per target country and direction. Which countries are in scope for Release 1?
3. Recording: retention periods, storage location and India residency; whether needed for the pilot.
4. WhatsApp: business verification status and owner of the WABA.
5. Messenger and Instagram: whether customer Pages will be connected in Release 1 (App Review).
6. SES: inbound receiving design and threading requirements.
7. Costs: quotations for every item in section 7.
8. Legal review of TRAI, DLT and consent obligations.

## 13. Exact next steps

1. Merge this documentation PR (owner approval).
2. Obtain the Exotel written pack (section 10).
3. Obtain the Twilio per-country validation for each target country and direction.
4. Open the Meta business verification and WABA ownership questions.
5. Confirm SES identity and inbound receiving design.
6. Only after the matching verification gate is met, start DFR1-011, then DFR1-027.

## 14. Source list

- Exotel call notifications: https://developer.exotel.com/docs/ip-pstn-webrtc/api-reference/call-notifications
- Exotel make-a-call API: https://developer.exotel.com/api/make-a-call-api
- Exotel number types FAQ: https://developer.exotel.com/docs/faqs/number-types
- Exotel migration blog (unverified pricing): https://exotel.com/blog/migrate-twilio-to-exotel-voice-ai-india/
- CloudTalk Exotel pricing guide (secondary): https://www.cloudtalk.io/blog/exotel-pricing/
- Twilio secure webhooks: https://www.twilio.com/docs/usage/webhooks/webhooks-security
- Twilio India voice guidelines: https://www.twilio.com/en-us/guidelines/in/voice
- Twilio India SMS guidelines: https://www.twilio.com/en-us/guidelines/in/sms
- Knowlarity integration guide (2013, secondary): https://www.scribd.com/document/202780359/Knowlarity-Sr-Integration-Guide-Jan-2013-2
- WhatsApp Business Platform pricing: https://developers.facebook.com/docs/whatsapp/pricing
- Messenger Platform overview: https://developers.facebook.com/docs/messenger-platform/overview
- Amazon SES sending process: https://docs.aws.amazon.com/ses/latest/dg/send-email-concepts-process.html
