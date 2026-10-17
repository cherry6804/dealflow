import { api } from "../lib/api";

export type ReferralStatus =
  | "NEW"
  | "CONTACTED"
  | "CONVERTED"
  | "NOT_CONVERTED";

export interface Referral {
  id: string;
  organization_id: string;
  customer_profile_id: string | null;
  referrer_contact_id: string | null;
  deal_id: string | null;
  referral_name: string;
  referral_phone: string | null;
  referral_email: string | null;
  status: ReferralStatus;
  notes: string | null;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ReferralListResponse {
  items: Referral[];
  total: number;
  page: number;
  page_size: number;
}

export interface ReferralListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: ReferralStatus;
}

export interface ReferralCreateInput {
  referral_name: string;
  referral_phone?: string | null;
  referral_email?: string | null;
  customer_profile_id?: string | null;
  referrer_contact_id?: string | null;
  deal_id?: string | null;
  status?: ReferralStatus;
  notes?: string | null;
}

export type ReferralUpdateInput = Partial<ReferralCreateInput>;

function buildQuery(params: ReferralListParams = {}): string {
  const query = new URLSearchParams();

  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.page_size ?? 10));

  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }

  if (params.status) {
    query.set("status", params.status);
  }

  return `?${query.toString()}`;
}

export const referralsApi = {
  list(params: ReferralListParams = {}): Promise<ReferralListResponse> {
    return api.get<ReferralListResponse>(
      `/referrals${buildQuery(params)}`,
    );
  },

  get(referralId: string): Promise<Referral> {
    return api.get<Referral>(
      `/referrals/${encodeURIComponent(referralId)}`,
    );
  },

  create(input: ReferralCreateInput): Promise<Referral> {
    return api.post<Referral>("/referrals", input);
  },

  update(
    referralId: string,
    input: ReferralUpdateInput,
  ): Promise<Referral> {
    return api.patch<Referral>(
      `/referrals/${encodeURIComponent(referralId)}`,
      input,
    );
  },

  deactivate(referralId: string): Promise<Referral> {
    return api.delete<Referral>(
      `/referrals/${encodeURIComponent(referralId)}`,
    );
  },
};