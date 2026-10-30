
import { api } from "../lib/api";

export type LeadStatus =
  | "NEW"
  | "CONTACTED"
  | "QUALIFIED"
  | "MATCHING"
  | "VISIT"
  | "NEGOTIATION"
  | "WON"
  | "LOST"
  | "ON_HOLD";

export type LeadInterest = "LOW" | "MEDIUM" | "HIGH";
export type LeadOutcome = "SUCCESSFUL" | "UNSUCCESSFUL";

export interface Lead {
  id: string;
  organization_id: string;
  contact_id: string;
  status: LeadStatus;
  interest: LeadInterest | null;
  outcome: LeadOutcome | null;
  owner_user_id: string | null;
  next_action: string | null;
  next_action_at: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LeadListResponse {
  items: Lead[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface LeadListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: LeadStatus;
  interest?: LeadInterest;
  outcome?: LeadOutcome;
  is_active?: boolean;
}

export interface LeadCreateInput {
  contact_id: string;
  interest?: LeadInterest | null;
  outcome?: LeadOutcome | null;
  next_action?: string | null;
  next_action_at?: string | null;
}

export interface LeadUpdateInput {
  status?: LeadStatus | null;
  interest?: LeadInterest | null;
  outcome?: LeadOutcome | null;
  owner_user_id?: string | null;
  next_action?: string | null;
  next_action_at?: string | null;
  is_active?: boolean;
}

function buildQuery(params: LeadListParams = {}): string {
  const query = new URLSearchParams();

  if (params.page !== undefined) {
    query.set("page", String(params.page));
  }
  if (params.page_size !== undefined) {
    query.set("page_size", String(params.page_size));
  }
  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }
  if (params.status) {
    query.set("status", params.status);
  }
  if (params.interest) {
    query.set("interest", params.interest);
  }
  if (params.outcome) {
    query.set("outcome", params.outcome);
  }
  if (params.is_active !== undefined) {
    query.set("is_active", String(params.is_active));
  }

  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export const leadsApi = {
  list(params: LeadListParams = {}): Promise<LeadListResponse> {
    return api.get<LeadListResponse>(`/leads${buildQuery(params)}`);
  },

  create(input: LeadCreateInput): Promise<Lead> {
    return api.post<Lead>("/leads", input);
  },

  update(leadId: string, input: LeadUpdateInput): Promise<Lead> {
    return api.patch<Lead>(
      `/leads/${encodeURIComponent(leadId)}`,
      input,
    );
  },
};
