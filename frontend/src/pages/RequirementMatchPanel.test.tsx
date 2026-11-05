import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { matchEvaluationApi, type MatchEvaluation, type MatchEvaluationResult } from "../services/matchEvaluationApi";
import RequirementMatchPanel from "./RequirementMatchPanel";

vi.mock("../services/matchEvaluationApi", () => ({
  matchEvaluationApi: {
    latest: vi.fn(),
    evaluate: vi.fn(),
    setTransactionType: vi.fn(),
    decide: vi.fn(),
  },
}));

const eligibleResult: MatchEvaluationResult = {
  property_id: "prop-1",
  rank: 1,
  eligibility: "eligible",
  overall_match: true,
  criteria: [],
  matched_factors: [{ criterion: "BUDGET", explanation: "Property price is within the configured budget bounds." }],
  unmatched_factors: [],
  missing_information: [],
  exclusion_reasons: [],
  ranking_basis: {},
  property: { id: "prop-1", locality: "Velachery", city: "Chennai", property_type: "APARTMENT", bhk: 2,
    transaction_type: "SALE", price: "7000000.00", rent: null, currency: "INR" },
};

const excludedResult: MatchEvaluationResult = {
  ...eligibleResult,
  property_id: "prop-2",
  rank: null,
  eligibility: "excluded",
  overall_match: false,
  matched_factors: [],
  unmatched_factors: [{ criterion: "TRANSACTION_TYPE", explanation: "The property is for rent but the requirement is for sale." }],
  exclusion_reasons: ["The property is for rent but the requirement is for sale."],
  property: { ...eligibleResult.property, id: "prop-2", transaction_type: "RENT" },
};

function evaluation(overrides: Partial<MatchEvaluation>): MatchEvaluation {
  return {
    run_id: "run-1",
    requirement_id: "req-1",
    evaluated_at: "2030-01-10T12:00:00+00:00",
    ruleset_version: "property-match-v1",
    next_best_action_ruleset_version: "next-best-action-v1",
    input_fingerprint: "abc",
    stale: false,
    total_candidates: 2,
    eligible_count: 1,
    results: [eligibleResult, excludedResult],
    recommendations: [
      {
        id: "rec-1",
        category: "review_property",
        basis: "deterministic_match",
        status: "open",
        priority: 1,
        summary: "Review 2 BHK, APARTMENT, Velachery, Chennai: eligible, rank 1 of 1.",
        subject_property_id: "prop-1",
        facts: {},
        ruleset_version: "next-best-action-v1",
        stale: false,
        history: [],
        decided_at: null,
      },
    ],
    disclaimer: "Rule-based matching. This is not a probability.",
    ...overrides,
  };
}

describe("RequirementMatchPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows eligible properties with their matched factors and excluded ones with the reason", async () => {
    vi.mocked(matchEvaluationApi.latest).mockResolvedValue(evaluation({}));
    render(<RequirementMatchPanel requirementId="req-1" transactionType="SALE" />);

    expect(await screen.findByText(/1 of 2 available properties are eligible/)).toBeTruthy();
    expect(screen.getByText(/Property price is within the configured budget bounds/)).toBeTruthy();
    expect(screen.getByText(/Excluded: The property is for rent/)).toBeTruthy();
    expect(screen.getByText(/This is not a probability/)).toBeTruthy();
  });

  it("marks stale results and does not let a member decide on them", async () => {
    vi.mocked(matchEvaluationApi.latest).mockResolvedValue(evaluation({ stale: true }));
    render(<RequirementMatchPanel requirementId="req-1" transactionType="SALE" />);

    expect(await screen.findByText(/changed after this evaluation/)).toBeTruthy();
    const accept = screen.getByRole("button", { name: "Accept" });
    expect((accept as HTMLButtonElement).disabled).toBe(true);
  });

  it("sends a decision with the member's reason", async () => {
    vi.mocked(matchEvaluationApi.latest).mockResolvedValue(evaluation({}));
    vi.mocked(matchEvaluationApi.decide).mockResolvedValue(evaluation({}).recommendations[0]);
    const user = userEvent.setup();
    render(<RequirementMatchPanel requirementId="req-1" transactionType="SALE" />);

    await screen.findByText(/Review 2 BHK/);
    const panel = screen.getByRole("heading", { name: "Matching and next actions" }).closest("section") as HTMLElement;
    await user.type(within(panel).getByLabelText("Reason (optional)"), "Customer liked the layout");
    await user.click(within(panel).getByRole("button", { name: "Accept" }));

    await waitFor(() =>
      expect(matchEvaluationApi.decide).toHaveBeenCalledWith("rec-1", "accepted", "Customer liked the layout"),
    );
  });

  it("shows that nothing has been evaluated rather than inventing results", async () => {
    vi.mocked(matchEvaluationApi.latest).mockResolvedValue(null);
    render(<RequirementMatchPanel requirementId="req-1" transactionType={null} />);

    expect(await screen.findByText("No evaluation has been run for this requirement yet.")).toBeTruthy();
  });
});
