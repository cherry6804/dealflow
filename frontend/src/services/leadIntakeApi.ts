import { api } from "../lib/api";

export type IntakeStatus = "invalid" | "received" | "needs_review" | "processed" | "rejected";

export interface IntakeSubmission {
  id: string;
  source_channel: "manual" | "form" | "api";
  external_reference: string;
  status: IntakeStatus;
  validation_problems: string[];
  normalized: { first_name: string; last_name: string | null; email: string | null; phone: string | null; interest: string | null } | null;
  match_outcome: string | null;
  candidate_contact_ids: string[];
  contact_id: string | null;
  lead_id: string | null;
  decision: string | null;
  decision_reason: string | null;
  created_at: string | null;
  processed_at: string | null;
}

export interface IntakeSubmitInput {
  source_channel: "manual" | "form" | "api";
  external_reference: string;
  payload: { first_name: string; last_name?: string; email?: string; phone?: string; interest?: string };
}

export interface QualificationFactor {
  key: string;
  label: string;
  points: number;
  max_points: number;
  known: boolean;
  observed: string | null;
}

export interface QualificationFindings {
  verified_crm_facts: {
    lead_status: string;
    lead_interest: string | null;
    contact_has_email: boolean;
    contact_has_phone: boolean;
    requirements_on_record: number;
  };
  rule_findings: {
    score: number;
    band: string;
    method: string;
    confidence: string;
    insufficient_data: boolean;
    ruleset_version: string;
    computed_at: string;
    factors: QualificationFactor[];
  };
  missing_information: Array<{ field: string; source: string }>;
  recommended_next_actions: Array<{ action: string; basis: string }>;
  ai_suggestions: Array<{ text: string; basis: string; verified: boolean }>;
  human_decisions: Array<{ decision: string; reason: string | null; decided_by_user_id: string; decided_at: string }>;
  escalation: { requires_review: boolean; reasons: string[] };
}

export interface QualificationResult {
  id: string;
  lead_id: string;
  execution_id: string;
  score_id: string;
  requires_review: boolean;
  review_status: "pending" | "accepted" | "overridden";
  review_reason: string | null;
  reviewed_at: string | null;
  created_at: string | null;
  stale: boolean;
  findings: QualificationFindings;
}

const BASE = "/lead-intake";

export const leadIntakeApi = {
  list() {
    return api.get<{ items: IntakeSubmission[] }>(BASE);
  },
  submit(input: IntakeSubmitInput) {
    return api.post<IntakeSubmission & { created: boolean }>(BASE, input);
  },
  process(submissionId: string) {
    return api.post<IntakeSubmission>(`${BASE}/${encodeURIComponent(submissionId)}/process`, {});
  },
  decide(submissionId: string, input: { decision: "attach" | "create_new" | "reject"; contact_id?: string; reason?: string }) {
    return api.post<IntakeSubmission>(`${BASE}/${encodeURIComponent(submissionId)}/decision`, input);
  },
  qualifications(leadId: string) {
    return api.get<{ items: QualificationResult[] }>(`/leads/${encodeURIComponent(leadId)}/qualifications`);
  },
  reviewQualification(qualificationId: string, input: { decision: "accept" | "override"; reason?: string }) {
    return api.post<QualificationResult>(
      `/lead-qualifications/${encodeURIComponent(qualificationId)}/review`,
      input,
    );
  },
};
