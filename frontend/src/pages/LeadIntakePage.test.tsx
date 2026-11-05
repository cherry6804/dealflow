import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { leadIntakeApi, type IntakeSubmission, type QualificationResult } from "../services/leadIntakeApi";
import LeadIntakePage from "./LeadIntakePage";

vi.mock("../services/leadIntakeApi", () => ({
  leadIntakeApi: {
    list: vi.fn(),
    submit: vi.fn(),
    process: vi.fn(),
    decide: vi.fn(),
    qualifications: vi.fn(),
    reviewQualification: vi.fn(),
  },
}));

const base: IntakeSubmission = {
  id: "sub-1",
  source_channel: "form",
  external_reference: "ref-1",
  status: "needs_review",
  validation_problems: [],
  normalized: { first_name: "Ravi", last_name: "Iyer", email: null, phone: "919876543210", interest: "HIGH" },
  match_outcome: "ambiguous",
  candidate_contact_ids: ["contact-a", "contact-b"],
  contact_id: null,
  lead_id: null,
  decision: null,
  decision_reason: null,
  created_at: null,
  processed_at: null,
};

const qualification: QualificationResult = {
  id: "qual-1",
  lead_id: "lead-1",
  execution_id: "exec-1",
  score_id: "score-1",
  requires_review: true,
  review_status: "pending",
  review_reason: null,
  reviewed_at: null,
  created_at: "2030-01-10T12:00:00+00:00",
  stale: false,
  findings: {
    verified_crm_facts: {
      lead_status: "NEW",
      lead_interest: "HIGH",
      contact_has_email: false,
      contact_has_phone: true,
      requirements_on_record: 0,
    },
    rule_findings: {
      score: 35,
      band: "low",
      method: "rule_based_baseline",
      confidence: "low",
      insufficient_data: true,
      ruleset_version: "priority-rules-v1",
      computed_at: "2030-01-10T12:00:00+00:00",
      factors: [{ key: "interest", label: "Stated interest", points: 25, max_points: 25, known: true, observed: "HIGH" }],
    },
    missing_information: [{ field: "budget", source: "priority_factor" }],
    recommended_next_actions: [{ action: "Record the customer's budget.", basis: "rule" }],
    ai_suggestions: [{ text: "Call this week.", basis: "ai_suggestion", verified: false }],
    human_decisions: [],
    escalation: { requires_review: true, reasons: ["insufficient_data"] },
  },
};

describe("LeadIntakePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an uncertain enquiry with a choice of candidates and never presents it as created", async () => {
    vi.mocked(leadIntakeApi.list).mockResolvedValue({ items: [base] });
    render(<LeadIntakePage />);

    expect(await screen.findByText(/Needs a person to decide/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach to candidate 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Attach to candidate 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create a new contact" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject enquiry" })).toBeTruthy();
  });

  it("sends the chosen candidate and the reason for the decision", async () => {
    vi.mocked(leadIntakeApi.list).mockResolvedValue({ items: [base] });
    vi.mocked(leadIntakeApi.decide).mockResolvedValue({ ...base, status: "processed" });
    const user = userEvent.setup();
    render(<LeadIntakePage />);

    const reason = await screen.findByLabelText("Reason for the decision");
    await user.type(reason, "Same household");
    await user.click(screen.getByRole("button", { name: "Attach to candidate 2" }));

    await waitFor(() =>
      expect(leadIntakeApi.decide).toHaveBeenCalledWith("sub-1", {
        decision: "attach",
        contact_id: "contact-b",
        reason: "Same household",
      }),
    );
  });

  it("labels an AI suggestion as unverified and keeps rule factors and missing information visible", async () => {
    vi.mocked(leadIntakeApi.list).mockResolvedValue({
      items: [{ ...base, status: "processed", match_outcome: "new_contact", lead_id: "lead-1", candidate_contact_ids: [] }],
    });
    vi.mocked(leadIntakeApi.qualifications).mockResolvedValue({ items: [qualification] });
    const user = userEvent.setup();
    render(<LeadIntakePage />);

    await user.click(await screen.findByRole("button", { name: "Show qualification for this lead" }));

    const panel = await screen.findByRole("article", { name: /Qualification recorded/ });
    expect(within(panel).getByText("Needs human review")).toBeTruthy();
    expect(within(panel).getByText("AI suggestion, unverified")).toBeTruthy();
    expect(within(panel).getByText(/Rule points from recorded facts, not a probability/)).toBeTruthy();
    expect(within(panel).getByRole("table")).toBeTruthy();
    expect(within(panel).getByText("budget")).toBeTruthy();
    expect(within(panel).getByText("Stated interest")).toBeTruthy();
  });

  it("requires a reason before an override is sent", async () => {
    vi.mocked(leadIntakeApi.list).mockResolvedValue({
      items: [{ ...base, status: "processed", match_outcome: "new_contact", lead_id: "lead-1", candidate_contact_ids: [] }],
    });
    vi.mocked(leadIntakeApi.qualifications).mockResolvedValue({ items: [qualification] });
    const user = userEvent.setup();
    render(<LeadIntakePage />);

    await user.click(await screen.findByRole("button", { name: "Show qualification for this lead" }));
    await user.click(await screen.findByRole("button", { name: "Override findings" }));

    expect(await screen.findByText("An override needs a reason before it is sent.")).toBeTruthy();
    expect(leadIntakeApi.reviewQualification).not.toHaveBeenCalled();
  });
});
