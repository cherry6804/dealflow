# DFR1-007 Channel provider comparison and capability matrix

- **Story:** DFR1-007, Confirm communication providers and channel capability matrix (Epic DFR1-E04, P0, 2 points, Sprint S1).
- **Status:** Research and comparison complete. **No provider is selected.** Provider selection is a product decision and is awaiting the owner's written choice.
- **Date of research:** 2026-11-05. Sources were fetched on that date. Provider pages change; re-check before contracting.
- **Scope:** Documentation only. No application code, no provider account, no sandbox, no credentials. Nothing in this document claims that a provider works with Dealsflo.

## 0. How to read the verification labels

- **Verified (official source):** stated on an official provider page fetched on 2026-11-05. The source link is given.
- **Reported (secondary):** found in search snippets or third-party guides only. Must be confirmed with the provider.
- **Assumption:** our planning assumption. Must be confirmed.
- **Not researched:** not covered in this pass.

## 1. Telephony (Exotel, Twilio, Knowlarity)

### 1.1 Facts by criterion

| Criterion | Exotel | Twilio | Knowlarity |
|---|---|---|---|
| Inbound call event | **Verified.** `incoming_call` event posted to a configured `popup_url`, with `call_sid`, `direction`, `from`, `to`, `exophone`, `timestamp`, `caller_info` ([Call Notifications](https://developer.exotel.com/docs/ip-pstn-webrtc/api-reference/call-notifications)). | **Verified.** Voice webhooks on a configured URL with `CallSid`, `From`, `To` and TwiML response ([Twilio voice docs](https://www.twilio.com/docs/usage/webhooks/webhooks-security) for signing; voice webhook fields not re-fetched). | **Reported.** End-of-call webhook and "What to do" HTTP hook that returns a forwarding number ([Knowlarity integration guide, 2013](https://www.scribd.com/document/202780359/Knowlarity-Sr-Integration-Guide-Jan-2013-2)). The current reference page did not load its content ([API reference](https://developer.knowlarity.com/api-reference)). |
| Webhook authentication | **Not documented.** The call notification page describes no signature, token or IP allowlist. **This is a blocker for DFR1-027 until Exotel confirms the mechanism.** | **Verified.** `X-Twilio-Signature`, HMAC-SHA1 over the URL and parameters with the auth token; JSON bodies covered by a `bodySHA256` query parameter; SDK validation recommended ([Secure webhooks](https://www.twilio.com/docs/usage/webhooks/webhooks-security)). No replay protection described. | **Not verified.** No signature or auth method found. |
| Webhook retry | **Verified.** Non-200 triggers retries at 5 s, 30 s and 5 min; dropped after three failed retries and logged ([Call Notifications](https://developer.exotel.com/docs/ip-pstn-webrtc/api-reference/call-notifications)). Dropped events need a reconciliation path. | Not re-fetched. Assumed retry behaviour: to confirm. | Not verified. |
| Answer and bridge | **Reported.** Call flows and "Connect two numbers" APIs exist ([Make a call API](https://developer.exotel.com/api/make-a-call-api)). Exact answer and bridge behaviour for an inbound call not verified. | **Reported.** TwiML `Dial`, `Enqueue` and `Conference` verbs are the usual mechanisms. Not re-fetched in this pass. | Reported. SIP configuration and streaming options exist, described as a Voice AI or UIC setup. |
| Human transfer | **Reported.** Achieved through call flow or connect APIs. To confirm for an active call. | **Reported.** Via `Dial` to an agent number or SIP endpoint. To confirm. | **Reported.** "What to do" hook returns a forwarding number. |
| Caller ID and status callbacks | `exophone` shows the dialled number. Status callbacks (`call_ringing`, `call_answered`, `call_completed`) verified above. | Status callbacks and `From`/`To` supported (usual). | Not verified. |
| Recording and consent | Not researched in detail. | India voice page: "Customers must obtain consent from the call recipient before sending commercial communications." Recording rules: **not stated** ([Twilio India voice](https://www.twilio.com/en-us/guidelines/in/voice)). | Not verified. |
| India numbers | **Reported.** ExoPhone (virtual/DID) and toll-free available; monthly rental per number. Plan prices from third-party sites only ([Number types FAQ](https://developer.exotel.com/docs/faqs/number-types)). | **Verified (restriction).** "Outbound calls to India can only be made from international (non-Indian) numbers." Toll-free numbers in India are not for outbound use ([India voice guidelines](https://www.twilio.com/en-us/guidelines/in/voice)). Local India number availability **not verified**. | Reported, not verified. |
| Sandbox / test numbers | **Not documented** on the pages fetched. Requires confirmation. | Twilio test credentials and trial accounts are standard; India-specific trial limits **not verified**. | **Not documented.** |
| Pricing | **Reported only.** Per-minute inbound rate is unpublished; third-party sources disagree (₹0.30–0.50 per minute vs ₹0.80–1.00 for outbound). Written quote required ([Exotel migration blog](https://exotel.com/blog/migrate-twilio-to-exotel-voice-ai-india/), [CloudTalk pricing guide](https://www.cloudtalk.io/blog/exotel-pricing/)). | Not researched in this pass. Use the Twilio India price list before budgeting. | Not researched. |
| Concurrency and limits | Not researched. | Not researched. Twilio flags high-volume short calls to Indian numbers as a block risk. | Not researched. |
| Regulatory | TRAI/DLT and telemarketer rules apply to commercial calling and SMS. Exotel-specific obligations **not researched**. | India guidelines say calls without recipient consent may be treated as Unsolicited Commercial Communication. Twilio recommends legal review ([India voice](https://www.twilio.com/en-us/guidelines/in/voice)). SMS in India requires DLT sender ID registration ([India SMS guide](https://www.twilio.com/en-us/guidelines/in/sms)). | Not researched. |
| Documentation and support | Call notification page is clear. Auth and sandbox missing. | Mature docs. Signature docs verified. | Documentation fragmented. Several pages did not load. |

### 1.2 Comparison matrix (telephony)

Scores: 1 weak, 2 adequate, 3 strong. "?" means not verified.

| Dimension | Exotel | Twilio | Knowlarity |
|---|---|---|---|
| Inbound webhook shape | 3 (verified) | 3 (verified) | ? |
| Webhook authentication | ? (blocker) | 3 (verified) | ? |
| Retry and delivery | 3 (verified) | 2 (assumed) | ? |
| Answer, bridge, transfer | 2 (reported) | 2 (reported) | 1–2 (reported, unclear) |
| India number availability | 3 (reported) | 1–2 (outbound restricted, local numbers unverified) | ? |
| Sandbox access | ? (not documented) | 2 (assumed, trial limits unverified) | ? |
| Pricing transparency | 1 (no public rate) | ? | ? |
| Integration complexity | 2 | 2 | ? |
| Security (signing, replay) | ? until confirmed | 3 (signing); replay guidance absent | ? |
| Scalability | ? | 3 (assumed, global platform) | ? |
| Developer experience | 2 | 3 | 1 (fragmented) |
| Reliability | 2 (retry policy documented) | 3 (assumed) | ? |
| Vendor dependency and portability | 2 | 2 | 2 |

### 1.3 Recommendation (for owner decision, not a selection)

- **Primary candidate: Exotel.** India-native, with the most complete verified inbound webhook contract of the three (event shape and retry policy). It is the best fit for Indian numbers and local compliance, which matters for real-estate customers. **Condition:** Exotel must confirm in writing how webhooks are authenticated (signature, token or allowlist), the sandbox process, and the answer, bridge and transfer behaviour before DFR1-027 starts.
- **Fallback candidate: Twilio.** The best-documented signing scheme and developer experience. **Caveats for India:** outbound calls to Indian numbers must originate from non-Indian numbers, toll-free numbers cannot be used for outbound, and voice OTP is not permitted. For a real-estate product that makes outbound follow-up calls to Indian numbers, this is a material constraint, so Twilio fits inbound-led use better than outbound-led use.
- **Not recommended yet: Knowlarity.** Documentation could not be verified (the current API reference did not load its content). Re-evaluate only if Knowlarity supplies current webhook and authentication documentation.

These are recommendations only. The owner decides.

## 2. WhatsApp Business

### 2.1 Facts

- **Meta rate card is INR for India.** Billing localisation for India began 1 January 2026 for eligible customers; migration to INR by 31 December 2026 ([WhatsApp pricing](https://developers.facebook.com/docs/whatsapp/pricing), verified).
- **Free service messages:** from 1 October 2026, each business phone number gets 1,000 free service messages per month; messages beyond that are charged ([WhatsApp pricing](https://developers.facebook.com/docs/whatsapp/pricing), verified).
- **India per-message amounts:** the official page did not show amounts (they are in a linked rate card file). Third-party sources report marketing ₹0.8631 and utility or authentication ₹0.115 per message before GST. **Reported, not verified.** Confirm against the rate card file before budgeting.
- **BSP:** platform fees are billed by the BSP on top of Meta's message charges. **Reported.** BSP list not researched in this pass.

### 2.2 Options

| Option | Notes | Status |
|---|---|---|
| Meta WhatsApp Business Platform, direct (Cloud API) | Official route. Requires Meta business verification and approved message templates for business-initiated messages. | Not verified for Dealsflo. Needs a Meta business account. |
| Official BSP (for example, a Meta-listed Tech Provider) | Simplifies onboarding and template management; adds platform fees. | Candidates not researched. Owner choice. |

## 3. Meta Messenger and Instagram

### 3.1 Facts (verified from [Messenger Platform overview](https://developers.facebook.com/docs/messenger-platform/overview), fetched 2026-11-05)

- Prerequisites: Meta developer account and app with the Messenger use case; a linked Facebook Page; an Instagram Professional account for Instagram Messaging; Business Verification if people without an app role will use it.
- **Standard Access** covers users with a role on the app or Page. **Advanced Access** needs App Review. App Review is not needed to message only your own Page.
- Permissions requested through Facebook Login for Business: `pages_show_list`, `pages_manage_metadata`, `pages_messaging`, `pages_read_engagement`, `business_management`; Instagram adds `instagram_basic`, `instagram_manage_messages`.
- **Standard messaging window:** 24 hours after a user's message. Up to 7 days after a Click-to-Messenger or Click-to-Direct ad.
- **Webhook signature:** the page did not state it. Meta's webhook signing (`X-Hub-Signature-256`) is the expected mechanism. **Reported; confirm in the Webhooks documentation.**

### 3.2 Fit for Dealsflo

Messenger and Instagram suit inbound lead enquiries from ads. Dealsflo would need Advanced Access for customers' Pages beyond its own, and App Review for that. This is a larger dependency than WhatsApp and is not needed for DFR1-027.

## 4. Email

### 4.1 Options researched

- **Amazon SES (candidate).** Verified from [SES sending process](https://docs.aws.amazon.com/ses/latest/dg/send-email-concepts-process.html): accepted requests return a message ID; bounce, complaint and auto-response notifications return to the sender by email or Amazon SNS; hard bounces to suppressed addresses are refused. **Not verified** from this pass: sandbox limits and production-access request steps, and domain-verification steps (confirm in the SES getting-started documentation before use).
- **Postmark, SendGrid, Zoho and others:** **not researched.** Listed as options for the owner to shortlist.
- **Existing SMTP settings:** account email already uses `EMAIL_SMTP_*` (`docs/product/release-1/E01-environment-and-provider-matrix.md`). That is not a business-email integration.

## 5. Cost assumptions (all to confirm)

- Telephony per-minute cost: unpublished for Exotel; confirm with a quote. Twilio: pull the India price list.
- WhatsApp: use the rate card file. Budget the free 1,000 service messages per number from 1 October 2026 and BSP fees separately.
- Email: SES is typically low cost per message; confirm with current SES pricing.

## 6. Compliance and security (summary)

- **TRAI/DLT:** commercial SMS and calls to Indian numbers are regulated. Sender registration and consent records are needed, and they must be checked with a legal adviser. Twilio's India guidance flags UCC risk without recipient consent.
- **Recording and consent:** Dealsflo must record consent before any recording or transcription (brief requirement). No provider page reviewed here defines the recording rule for Indian calls. Confirm per provider.
- **Webhook security:** Twilio signs with HMAC-SHA1 (verified). Exotel signing is unknown. Dealsflo's own verifier (DFR1-012) is provider-neutral, so a provider-specific verifier is added only after selection.
- **Secrets:** all credentials go through the DFR1-011 connection registry and secrets boundary. None are stored in configuration files.

## 7. Required sandbox and account prerequisites (per selection)

- **Exotel:** account and ExoPhone with India number; API key and token; written confirmation of webhook authentication and sandbox access.
- **Twilio:** account, test credentials, an India-capable number (if local India numbers are needed, confirm availability and regulatory bundle), and a DLT registration for SMS.
- **WhatsApp:** Meta business account, business verification, WABA, phone number, approved templates, BSP if used.
- **Messenger and Instagram:** Meta app, Page, Instagram Professional account, App Review for Advanced Access.
- **Email:** verified sending domain and SES identity, production access request.

No account for any of these exists in this repository. Nothing was created.

## 8. Unresolved questions (owner or provider to answer)

1. Telephony provider selection (Exotel or Twilio, or another).
2. Exotel: how are webhooks authenticated? Is there a sandbox? Confirm the answer, bridge and transfer flow for an inbound call.
3. Twilio: Indian local number availability for inbound use. Trial limits for India.
4. Outbound calling to Indian numbers: which provider and number type will you use? Twilio cannot originate outbound calls to Indian numbers from Indian numbers.
5. Call recording: is it in scope for Release 1? Consent wording and storage location.
6. WhatsApp: direct Cloud API or BSP? Which BSP?
7. Messenger and Instagram: will customers' Pages be connected, which requires App Review?
8. Email: SES or another provider?
9. Budget: approve the cost assumptions above.

## 9. Impact on DFR1-011 and DFR1-027

- **DFR1-011 (connection registry):** the registry is provider-neutral and already on develop for OpenAI. A telephony provider adds a provider key, credential fields, and a connection probe. Probes stay unregistered until selection. No change is made to the registry in this story.
- **DFR1-027 (inbound lifecycle):** blocked until (a) the owner selects a telephony provider, (b) the provider confirms webhook authentication in writing, and (c) a sandbox account exists. Without (b), DFR1-027 cannot verify inbound webhooks against the provider, and the story can only be mocked.
- **DFR1-012 (already merged):** the synthetic `hmac_sha256_v1` verifier must not be presented as a provider format. A provider adapter adds its own verifier through the registered contract.

## 10. Exact next steps

1. Owner selects the telephony provider (or confirms the recommendation, or asks for a different candidate).
2. Owner decides the WhatsApp route (direct or BSP) and whether Messenger and Instagram are in Release 1.
3. Owner confirms the email provider.
4. Send questions 2 to 5 above to the selected telephony provider and record the written answers as an addendum to this document.
5. Obtain a sandbox account and record its identifiers (not credentials) in the E01 matrix.
6. Only then start provider-specific work (adapter, probe and verifier), in DFR1-027 and DFR1-011 follow-ups.

## 11. Source list

- Exotel call notifications: https://developer.exotel.com/docs/ip-pstn-webrtc/api-reference/call-notifications
- Exotel make-a-call API: https://developer.exotel.com/api/make-a-call-api
- Exotel number types FAQ: https://developer.exotel.com/docs/faqs/number-types
- Exotel migration blog: https://exotel.com/blog/migrate-twilio-to-exotel-voice-ai-india/
- CloudTalk Exotel pricing guide: https://www.cloudtalk.io/blog/exotel-pricing/
- Twilio secure webhooks: https://www.twilio.com/docs/usage/webhooks/webhooks-security
- Twilio India voice guidelines: https://www.twilio.com/en-us/guidelines/in/voice
- Twilio India SMS guidelines: https://www.twilio.com/en-us/guidelines/in/sms
- Knowlarity integration guide (2013, secondary): https://www.scribd.com/document/202780359/Knowlarity-Sr-Integration-Guide-Jan-2013-2
- Knowlarity API reference (content not loaded): https://developer.knowlarity.com/api-reference
- WhatsApp Business Platform pricing: https://developers.facebook.com/docs/whatsapp/pricing
- Messenger Platform overview: https://developers.facebook.com/docs/messenger-platform/overview
- Amazon SES sending process: https://docs.aws.amazon.com/ses/latest/dg/send-email-concepts-process.html
- Third-party WhatsApp rate summaries (secondary, not used as facts): myoperator.com, chatmaxima.com, 2factor.in (search results only)
