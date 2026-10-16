import { api } from "../lib/api";

export type SiteVisitStatus = "SCHEDULED" | "COMPLETED" | "CANCELLED" | "NO_SHOW";

export interface SiteVisitCreateInput {
  property_id: string;
  lead_id?: string | null;
  customer_profile_id?: string | null;
  owner_user_id?: string | null;
  scheduled_at: string;
  ends_at?: string | null;
  notes?: string | null;
}

export interface SiteVisit {
  id: string;
  organization_id: string;
  property_id: string;
  lead_id: string | null;
  customer_profile_id: string | null;
  owner_user_id: string;
  scheduled_at: string;
  ends_at: string | null;
  status: SiteVisitStatus;
  outcome: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface SiteVisitListResponse {
  items: SiteVisit[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const siteVisitsApi = {
  schedule(input: SiteVisitCreateInput): Promise<SiteVisit> {
    return api.post<SiteVisit>("/site-visits", input);
  },

  list(params: { page?: number; page_size?: number; status?: SiteVisitStatus | "" } = {}): Promise<SiteVisitListResponse> {
    const query = new URLSearchParams();
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.page_size ?? 10));
    if (params.status) query.set("status", params.status);
    return api.get<SiteVisitListResponse>(`/site-visits?${query.toString()}`);
  },
};
