
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

export interface DealStageTransitionInput {
  stage: DealStage;
  reason?: string | null;
}

export interface DealStageHistoryItem {
  id: string;
  organization_id: string;
  deal_id: string;
  from_stage: string;
  to_stage: string;
  actor_user_id: string | null;
  reason: string | null;
  created_at: string;
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

// -----------------------------------------------------------------------------
// Payment milestones
// -----------------------------------------------------------------------------

export type PaymentMilestoneStatus = "PENDING" | "PAID" | "CANCELLED";

export interface PaymentMilestone {
  id: string;
  organization_id: string;
  deal_id: string;
  name: string;
  amount: number | string;
  currency: string;
  due_at: string;
  notes: string | null;
  status: PaymentMilestoneStatus;
  paid_at: string | null;
  payment_reference: string | null;
  paid_by_user_id: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  is_overdue: boolean;
}

export interface PaymentMilestoneListResponse {
  items: PaymentMilestone[];
  total: number;
}

export interface PaymentMilestoneCreateInput {
  name: string;
  amount: number;
  currency: string;
  due_at: string;
  notes?: string | null;
}

export interface PaymentMilestoneUpdateInput {
  name?: string;
  amount?: number;
  currency?: string;
  due_at?: string;
  notes?: string | null;
}

export interface PaymentMilestoneMarkPaidInput {
  payment_reference?: string | null;
}

export const paymentMilestonesApi = {
  list(dealId: string): Promise<PaymentMilestoneListResponse> {
    return api.get<PaymentMilestoneListResponse>(
      `/deals/${encodeURIComponent(dealId)}/payment-milestones`,
    );
  },

  create(
    dealId: string,
    input: PaymentMilestoneCreateInput,
  ): Promise<PaymentMilestone> {
    return api.post<PaymentMilestone>(
      `/deals/${encodeURIComponent(dealId)}/payment-milestones`,
      input,
    );
  },

  update(
    milestoneId: string,
    input: PaymentMilestoneUpdateInput,
  ): Promise<PaymentMilestone> {
    return api.patch<PaymentMilestone>(
      `/payment-milestones/${encodeURIComponent(milestoneId)}`,
      input,
    );
  },

  markPaid(
    milestoneId: string,
    input: PaymentMilestoneMarkPaidInput = {},
  ): Promise<PaymentMilestone> {
    return api.post<PaymentMilestone>(
      `/payment-milestones/${encodeURIComponent(milestoneId)}/mark-paid`,
      input,
    );
  },

  cancel(milestoneId: string): Promise<PaymentMilestone> {
    return api.post<PaymentMilestone>(
      `/payment-milestones/${encodeURIComponent(milestoneId)}/cancel`,
    );
  },
};

// -----------------------------------------------------------------------------
// Deal commissions — DF-120
// -----------------------------------------------------------------------------

export type DealCommissionType = "FIXED" | "PERCENTAGE";

export type DealCommissionStatus =
  | "PROPOSED"
  | "AGREED"
  | "PAID"
  | "CANCELLED";

export interface DealCommission {
  id: string;
  organization_id: string;
  deal_id: string;
  commission_type: DealCommissionType;
  fixed_amount: number | string | null;
  rate_percent: number | string | null;
  currency: string;
  status: DealCommissionStatus;
  terms: string | null;
  agreed_at: string | null;
  paid_at: string | null;
  payment_reference: string | null;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  calculated_amount: number | string | null;
}

export interface DealCommissionListResponse {
  items: DealCommission[];
  total: number;
}

export type DealCommissionCreateInput =
  | {
      commission_type: "FIXED";
      fixed_amount: number;
      rate_percent?: never;
      currency: string;
      terms?: string | null;
    }
  | {
      commission_type: "PERCENTAGE";
      rate_percent: number;
      fixed_amount?: never;
      currency: string;
      terms?: string | null;
    };

export interface DealCommissionUpdateInput {
  commission_type?: DealCommissionType;
  fixed_amount?: number | null;
  rate_percent?: number | null;
  currency?: string;
  terms?: string | null;
}

export interface DealCommissionPaymentInput {
  payment_reference?: string | null;
}

export const dealCommissionsApi = {
  list(dealId: string): Promise<DealCommissionListResponse> {
    return api.get<DealCommissionListResponse>(
      `/deals/${encodeURIComponent(dealId)}/commissions`,
    );
  },

  get(commissionId: string): Promise<DealCommission> {
    return api.get<DealCommission>(
      `/commissions/${encodeURIComponent(commissionId)}`,
    );
  },

  create(
    dealId: string,
    input: DealCommissionCreateInput,
  ): Promise<DealCommission> {
    return api.post<DealCommission>(
      `/deals/${encodeURIComponent(dealId)}/commissions`,
      input,
    );
  },

  update(
    commissionId: string,
    input: DealCommissionUpdateInput,
  ): Promise<DealCommission> {
    return api.patch<DealCommission>(
      `/commissions/${encodeURIComponent(commissionId)}`,
      input,
    );
  },

  agree(commissionId: string): Promise<DealCommission> {
    return api.post<DealCommission>(
      `/commissions/${encodeURIComponent(commissionId)}/agree`,
    );
  },

  markPaid(
    commissionId: string,
    input: DealCommissionPaymentInput = {},
  ): Promise<DealCommission> {
    return api.post<DealCommission>(
      `/commissions/${encodeURIComponent(commissionId)}/mark-paid`,
      input,
    );
  },

  cancel(commissionId: string): Promise<DealCommission> {
    return api.post<DealCommission>(
      `/commissions/${encodeURIComponent(commissionId)}/cancel`,
    );
  },
};

// -----------------------------------------------------------------------------
// Deal listing and stage management
// -----------------------------------------------------------------------------

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

  transitionStage(
    dealId: string,
    input: DealStageTransitionInput,
  ): Promise<Deal> {
    return api.patch<Deal>(
      `/deals/${encodeURIComponent(dealId)}/stage`,
      input,
    );
  },
};

// -----------------------------------------------------------------------------
// Deal negotiations
// -----------------------------------------------------------------------------

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
