
import { api } from "../lib/api";

export type DealStage =
  | "NEW"
  | "QUALIFICATION"
  | "NEGOTIATION"
  | "BOOKING"
  | "CLOSED_WON"
  | "CLOSED_LOST";

export interface Deal {
  id: string;
  organization_id: string;
  customer_profile_id: string;
  property_id: string;
  lead_id: string | null;
  owner_user_id: string;
  stage: DealStage | string;
  expected_value: number | string | null;
  currency: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  owner_name: string | null;
}

export interface DealListResponse {
  items: Deal[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface DealListParams {
  page?: number;
  page_size?: number;
  stage?: DealStage;
  owner_user_id?: string;
}

export interface DealCreateInput {
  customer_profile_id: string;
  property_id: string;
  lead_id?: string | null;
  owner_user_id?: string | null;
  stage?: DealStage;
  expected_value?: number | null;
  currency?: string;
  notes?: string | null;
}

export type NegotiationState =
  | "IN_PROGRESS"
  | "WAITING_ON_CUSTOMER"
  | "WAITING_ON_SELLER"
  | "TERMS_AGREED"
  | "STALLED"
  | "COMPLETED"
  | "CANCELLED";

export interface DealNegotiation {
  id: string;
  organization_id: string;
  deal_id: string;
  state: NegotiationState;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface NegotiationHistoryItem {
  id: string;
  organization_id: string;
  negotiation_id: string;
  from_state: NegotiationState | null;
  to_state: NegotiationState;
  actor_user_id: string | null;
  note: string | null;
  created_at: string;
}

export interface NegotiationHistoryResponse {
  items: NegotiationHistoryItem[];
  total: number;
}

export interface NegotiationCreateInput {
  state?: NegotiationState;
  note?: string | null;
}

export interface NegotiationUpdateInput {
  state: NegotiationState;
  note?: string | null;
}

function buildQuery(params: DealListParams = {}): string {
  const query = new URLSearchParams();

  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.page_size ?? 20));

  if (params.stage) {
    query.set("stage", params.stage);
  }

  if (params.owner_user_id) {
    query.set("owner_user_id", params.owner_user_id);
  }

  return `?${query.toString()}`;
}

export const dealsApi = {
  list(params: DealListParams = {}): Promise<DealListResponse> {
    return api.get<DealListResponse>(`/deals${buildQuery(params)}`);
  },

  get(dealId: string): Promise<Deal> {
    return api.get<Deal>(`/deals/${encodeURIComponent(dealId)}`);
  },

  create(input: DealCreateInput): Promise<Deal> {
    return api.post<Deal>("/deals", input);
  },
};

export const dealNegotiationsApi = {
  get(dealId: string): Promise<DealNegotiation> {
    return api.get<DealNegotiation>(
      `/deals/${encodeURIComponent(dealId)}/negotiation`,
    );
  },

  create(
    dealId: string,
    input: NegotiationCreateInput = {},
  ): Promise<DealNegotiation> {
    return api.post<DealNegotiation>(
      `/deals/${encodeURIComponent(dealId)}/negotiation`,
      input,
    );
  },

  update(
    dealId: string,
    input: NegotiationUpdateInput,
  ): Promise<DealNegotiation> {
    return api.patch<DealNegotiation>(
      `/deals/${encodeURIComponent(dealId)}/negotiation`,
      input,
    );
  },

  history(dealId: string): Promise<NegotiationHistoryResponse> {
    return api.get<NegotiationHistoryResponse>(
      `/deals/${encodeURIComponent(dealId)}/negotiation/history`,
    );
  },
};
