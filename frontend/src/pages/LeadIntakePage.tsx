import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../lib/api";
import {
  leadIntakeApi,
  type IntakeSubmission,
  type QualificationResult,
} from "../services/leadIntakeApi";

import "./LeadIntakePage.css";

const INTEREST_OPTIONS = ["", "LOW", "MEDIUM", "HIGH"] as const;

interface IntakeForm {
  channel: "manual" | "form" | "api";
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  interest: string;
}

const EMPTY_FORM: IntakeForm = { channel: "manual", firstName: "", lastName: "", email: "", phone: "", interest: "" };

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.details as { detail?: { reason?: string; problems?: string[] } | string } | undefined;
    const inner = detail?.detail;
    if (inner && typeof inner === "object") {
      const problems = inner.problems?.length ? ` ${inner.problems.join(" ")}` : "";
      return `${inner.reason ?? "The request was refused."}${problems}`;
    }
    if (typeof inner === "string") {
      return inner;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

function newReference(): string {
  return `ui-${crypto.randomUUID()}`;
}

function statusLabel(status: IntakeSubmission["status"]): string {
  switch (status) {
    case "invalid":
      return "Invalid, not processed";
    case "received":
      return "Received, waiting to be processed";
    case "needs_review":
      return "Needs a person to decide";
    case "processed":
      return "Processed into the CRM";
    case "rejected":
      return "Rejected by a person";
  }
}

function outcomeLabel(outcome: string | null): string {
  switch (outcome) {
    case "new_contact":
      return "New contact and lead";
    case "matched_contact":
      return "Matched an existing contact";
    case "matched_open_lead":
      return "Matched an open lead, no new lead";
    case "ambiguous":
      return "Could match more than one contact";
    default:
      return "Not yet resolved";
  }
}

function QualificationPanel({ leadId, onChanged }: { leadId: string; onChanged: () => void }) {
  const [items, setItems] = useState<QualificationResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reviewReason, setReviewReason] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const response = await leadIntakeApi.qualifications(leadId);
      setItems(response.items);
      setError(null);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function review(result: QualificationResult, decision: "accept" | "override") {
    const reason = reviewReason[result.id]?.trim() || undefined;
    if (decision === "override" && !reason) {
      setError("An override needs a reason before it is sent.");
      return;
    }
    try {
      await leadIntakeApi.reviewQualification(result.id, { decision, reason });
      await load();
      onChanged();
    } catch (caught) {
      setError(messageFor(caught));
    }
  }

  if (error) {
    return <p role="alert" className="intake-alert">{error}</p>;
  }
  if (items.length === 0) {
    return <p className="intake-subtle">No qualification has been recorded for this lead yet.</p>;
  }

  return (
    <div className="intake-qualifications">
      {items.map((result) => {
        const findings = result.findings;
        return (
          <article key={result.id} className="intake-qualification" aria-label={`Qualification recorded ${result.created_at ?? ""}`}>
            <p>
              <span className={result.requires_review ? "intake-badge intake-badge-warn" : "intake-badge"}>
                {result.requires_review ? "Needs human review" : "No escalation"}
              </span>{" "}
              Review status: <strong>{result.review_status}</strong>
              {result.stale ? (
                <span className="intake-badge intake-badge-warn"> The lead changed after these findings were recorded.</span>
              ) : null}
            </p>

            <h4>Verified CRM facts</h4>
            <p className="intake-subtle">
              Read from the lead and contact at the time of the run. Status {findings.verified_crm_facts.lead_status}, interest{" "}
              {findings.verified_crm_facts.lead_interest ?? "not recorded"}, email {findings.verified_crm_facts.contact_has_email ? "on file" : "missing"},
              phone {findings.verified_crm_facts.contact_has_phone ? "on file" : "missing"}, requirements on record{" "}
              {findings.verified_crm_facts.requirements_on_record}.
            </p>

            <h4>
              Rule-based score: {findings.rule_findings.score} ({findings.rule_findings.band}, {findings.rule_findings.method},
              confidence {findings.rule_findings.confidence})
            </h4>
            <p className="intake-subtle">
              Rule points from recorded facts, not a probability. Ruleset {findings.rule_findings.ruleset_version}, computed{" "}
              {new Date(findings.rule_findings.computed_at).toLocaleString()}.
              {findings.rule_findings.insufficient_data ? " Too few facts for a full rule evaluation, so this is a baseline." : ""}
            </p>
            <table className="intake-table">
              <caption>Factors that set the score</caption>
              <thead>
                <tr>
                  <th scope="col">Factor</th>
                  <th scope="col">Points</th>
                  <th scope="col">Observed value</th>
                </tr>
              </thead>
              <tbody>
                {findings.rule_findings.factors.map((factor) => (
                  <tr key={factor.key}>
                    <td>{factor.label}</td>
                    <td>
                      {factor.points} of {factor.max_points}
                    </td>
                    <td>{factor.known ? (factor.observed ?? "none") : "Not recorded"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h4>Missing information</h4>
            {findings.missing_information.length === 0 ? (
              <p className="intake-subtle">Nothing recorded as missing.</p>
            ) : (
              <ul>
                {findings.missing_information.map((item) => (
                  <li key={`${item.source}-${item.field}`}>{item.field}</li>
                ))}
              </ul>
            )}

            <h4>Recommended next actions</h4>
            <ul>
              {findings.recommended_next_actions.map((item) => (
                <li key={item.action}>
                  {item.action} <span className="intake-subtle">(basis: rule)</span>
                </li>
              ))}
            </ul>

            <h4>AI suggestions</h4>
            {findings.ai_suggestions.length === 0 ? (
              <p className="intake-subtle">No AI suggestion was recorded.</p>
            ) : (
              <ul>
                {findings.ai_suggestions.map((item) => (
                  <li key={item.text}>
                    {item.text} <span className="intake-badge">AI suggestion, unverified</span>
                  </li>
                ))}
              </ul>
            )}

            <h4>Human decisions</h4>
            {findings.human_decisions.length === 0 ? (
              <p className="intake-subtle">No person has reviewed these findings yet.</p>
            ) : (
              <ul>
                {findings.human_decisions.map((item) => (
                  <li key={item.decided_at}>
                    {item.decision}
                    {item.reason ? `: ${item.reason}` : ""} <span className="intake-subtle">(member {item.decided_by_user_id})</span>
                  </li>
                ))}
              </ul>
            )}

            {result.review_status === "pending" ? (
              <div className="intake-review">
                <label>
                  Reason (required to override)
                  <input
                    value={reviewReason[result.id] ?? ""}
                    onChange={(event) => setReviewReason({ ...reviewReason, [result.id]: event.target.value })}
                    maxLength={500}
                  />
                </label>
                <button type="button" className="intake-button" onClick={() => void review(result, "accept")}>
                  Accept findings
                </button>
                <button type="button" className="intake-button intake-button-secondary" onClick={() => void review(result, "override")}>
                  Override findings
                </button>
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

export default function LeadIntakePage() {
  const [submissions, setSubmissions] = useState<IntakeSubmission[]>([]);
  const [form, setForm] = useState<IntakeForm>(EMPTY_FORM);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [decisionReason, setDecisionReason] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await leadIntakeApi.list();
      setSubmissions(response.items);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      await load();
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload: { first_name: string; last_name?: string; email?: string; phone?: string; interest?: string } = {
      first_name: form.firstName.trim(),
    };
    if (form.lastName.trim()) payload.last_name = form.lastName.trim();
    if (form.email.trim()) payload.email = form.email.trim();
    if (form.phone.trim()) payload.phone = form.phone.trim();
    if (form.interest) payload.interest = form.interest;
    void run(async () => {
      await leadIntakeApi.submit({ source_channel: form.channel, external_reference: newReference(), payload });
      setForm(EMPTY_FORM);
    }, "The enquiry was stored. Process it to create or match the contact and lead.");
  }

  return (
    <main className="intake-page">
      <header className="intake-header">
        <h1>Lead intake</h1>
        <p className="intake-subtle">
          Enquiries are stored as received. A person checks any uncertain match before a contact or lead is created.
        </p>
      </header>

      {error ? <p role="alert" className="intake-alert">{error}</p> : null}
      {notice ? <p role="status" className="intake-notice">{notice}</p> : null}

      <section aria-labelledby="intake-form-title" className="intake-panel">
        <h2 id="intake-form-title">Record an enquiry</h2>
        <form onSubmit={submit} className="intake-form">
          <label>
            Source
            <select value={form.channel} onChange={(event) => setForm({ ...form, channel: event.target.value as IntakeForm["channel"] })}>
              <option value="manual">Entered by hand</option>
              <option value="form">Web form</option>
              <option value="api">API</option>
            </select>
          </label>
          <label>
            First name
            <input value={form.firstName} onChange={(event) => setForm({ ...form, firstName: event.target.value })} required />
          </label>
          <label>
            Last name
            <input value={form.lastName} onChange={(event) => setForm({ ...form, lastName: event.target.value })} />
          </label>
          <label>
            Email
            <input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
          </label>
          <label>
            Phone
            <input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} />
          </label>
          <label>
            Interest
            <select value={form.interest} onChange={(event) => setForm({ ...form, interest: event.target.value })}>
              {INTEREST_OPTIONS.map((option) => (
                <option key={option || "none"} value={option}>
                  {option || "Not stated"}
                </option>
              ))}
            </select>
          </label>
          <p className="intake-subtle">An email address or a phone number is needed to identify the person.</p>
          <button type="submit" className="intake-button" disabled={busy}>
            Store enquiry
          </button>
        </form>
      </section>

      <section aria-labelledby="intake-list-title" className="intake-panel">
        <h2 id="intake-list-title">Enquiries</h2>
        {submissions.length === 0 ? <p className="intake-subtle">No enquiries yet.</p> : null}
        <ul className="intake-list">
          {submissions.map((item) => (
            <li key={item.id} className="intake-item">
              <p>
                <strong>{statusLabel(item.status)}</strong> · {item.source_channel} · {outcomeLabel(item.match_outcome)}
              </p>
              {item.validation_problems.length > 0 ? (
                <ul>
                  {item.validation_problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              ) : null}
              {item.status === "received" ? (
                <button type="button" className="intake-button" disabled={busy} onClick={() => void run(() => leadIntakeApi.process(item.id), "Enquiry processed.")}>
                  Process enquiry
                </button>
              ) : null}
              {item.status === "needs_review" ? (
                <div className="intake-review">
                  <p>
                    {item.candidate_contact_ids.length} existing contact(s) share an email or phone with this enquiry. Choose one, create a
                    new contact, or reject the enquiry.
                  </p>
                  {item.candidate_contact_ids.map((contactId, index) => (
                    <button
                      key={contactId}
                      type="button"
                      className="intake-button intake-button-secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => leadIntakeApi.decide(item.id, { decision: "attach", contact_id: contactId, reason: decisionReason[item.id] }),
                          "Enquiry attached to the chosen contact.",
                        )
                      }
                    >
                      Attach to candidate {index + 1}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="intake-button intake-button-secondary"
                    disabled={busy}
                    onClick={() => void run(() => leadIntakeApi.decide(item.id, { decision: "create_new", reason: decisionReason[item.id] }), "New contact created.")}
                  >
                    Create a new contact
                  </button>
                  <label>
                    Reason for the decision
                    <input
                      value={decisionReason[item.id] ?? ""}
                      maxLength={500}
                      onChange={(event) => setDecisionReason({ ...decisionReason, [item.id]: event.target.value })}
                    />
                  </label>
                  <button
                    type="button"
                    className="intake-button intake-button-secondary"
                    disabled={busy}
                    onClick={() => void run(() => leadIntakeApi.decide(item.id, { decision: "reject", reason: decisionReason[item.id] }), "Enquiry rejected.")}
                  >
                    Reject enquiry
                  </button>
                </div>
              ) : null}
              {item.status === "processed" && item.lead_id ? (
                <button type="button" className="intake-button intake-button-secondary" onClick={() => setSelectedLeadId(item.lead_id)}>
                  Show qualification for this lead
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      {selectedLeadId ? (
        <section aria-labelledby="qualification-title" className="intake-panel">
          <h2 id="qualification-title">Qualification</h2>
          <QualificationPanel leadId={selectedLeadId} onChanged={() => void load()} />
        </section>
      ) : null}
    </main>
  );
}
