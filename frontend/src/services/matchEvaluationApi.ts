import { api } from "../lib/api";

export type MatchEligibility = "eligible" | "excluded" | "insufficient_data";
export type RecommendationStatus = "open" | "accepted" | "dismissed" | "done";
export type TransactionType = "SALE" | "RENT" | "LEASE";

export interface MatchCriterion {
  criterion: "LOCATION" | "PROPERTY_TYPE_AND_BHK" | "BUDGET" | "TRANSACTION_TYPE";
  status: "MATCH" | "MISMATCH" | "UNKNOWN" | "NOT_CONFIGURED";
  explanation: string;
}

export interface MatchExplanationItem {
  criterion: string;
  explanation: string;
}

export interface MatchEvaluationResult {
  property_id: string;
  rank: number | null;
  eligibility: MatchEligibility;
  overall_match: boolean;
  criteria: MatchCriterion[];
  matched_factors: MatchExplanationItem[];
  unmatched_factors: MatchExplanationItem[];
  missing_information: MatchExplanationItem[];
  exclusion_reasons: string[];
  ranking_basis: Record<string, unknown>;
  property: {
    id: string;
    locality: string | null;
    city: string | null;
    property_type: string | null;
    bhk: number | null;
    transaction_type: string | null;
    price: string | null;
    rent: string | null;
    currency: string | null;
  };
}

export interface NextBestAction {
  id: string;
  category: string;
  basis: "verified_fact" | "deterministic_match" | "missing_information" | "ai_suggestion";
  status: RecommendationStatus;
  priority: number;
  summary: string;
  subject_property_id: string | null;
  facts: Record<string, unknown>;
  ruleset_version: string;
  stale: boolean;
  history: Array<{ from: string; to: string; by: string; at: string; reason: string | null }>;
  decided_at: string | null;
}

export interface MatchEvaluation {
  run_id: string;
  requirement_id: string;
  evaluated_at: string | null;
  ruleset_version: string | null;
  next_best_action_ruleset_version: string;
  input_fingerprint: string | null;
  stale: boolean;
  total_candidates: number;
  eligible_count: number;
  results: MatchEvaluationResult[];
  recommendations: NextBestAction[];
  disclaimer: string;
}

const BASE = "/customer-requirements";

export const matchEvaluationApi = {
  latest(requirementId: string) {
    return api.get<MatchEvaluation | null>(`${BASE}/${encodeURIComponent(requirementId)}/match-evaluations/latest`);
  },
  evaluate(requirementId: string) {
    return api.post<MatchEvaluation & { created: boolean }>(
      `${BASE}/${encodeURIComponent(requirementId)}/match-evaluations`,
      {},
    );
  },
  setTransactionType(requirementId: string, transactionType: TransactionType | null) {
    return api.put<{ id: string; transaction_type: TransactionType | null }>(
      `${BASE}/${encodeURIComponent(requirementId)}/transaction-type`,
      { transaction_type: transactionType },
    );
  },
  decide(recommendationId: string, decision: "accepted" | "dismissed" | "done", reason?: string) {
    return api.post<NextBestAction>(`/next-best-actions/${encodeURIComponent(recommendationId)}/feedback`, {
      decision,
      reason,
    });
  },
};
