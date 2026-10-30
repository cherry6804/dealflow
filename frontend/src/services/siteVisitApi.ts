
import { api } from "../lib/api";

export type SiteVisitStatus =
  | "SCHEDULED"
  | "COMPLETED"
  | "CANCELLED"
  | "NO_SHOW";

export type SiteVisitOutcome =
  | "INTERESTED"
  | "NOT_INTERESTED"
  | "NEGOTIATION"
  | "FOLLOW_UP_REQUIRED"
  | "OTHER";

export interface SiteVisitCreateInput {
  property_id: string;
  lead_id?: string | null;
  customer_profile_id?: string | null;
  owner_user_id?: string | null;
  scheduled_at: string;
  ends_at?: string | null;
  notes?: string | null;
}

export interface SiteVisitAttendanceInput {
  status: Exclude<SiteVisitStatus, "SCHEDULED">;
  outcome?: SiteVisitOutcome | null;
  feedback?: string | null;
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
  outcome: SiteVisitOutcome | null;
  notes: string | null;
  feedback: string | null;
  created_at: string;
  updated_at: string;
  has_follow_up: boolean;
}

export interface SiteVisitListResponse {
  items: SiteVisit[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface SiteVisitListParams {
  page?: number;
  page_size?: number;
  status?: SiteVisitStatus | "";
  lead_id?: string;
  customer_profile_id?: string;
  property_id?: string;
}

export const siteVisitsApi = {
  schedule(input: SiteVisitCreateInput): Promise<SiteVisit> {
    return api.post<SiteVisit>("/site-visits", input);
  },

  list(
    params: SiteVisitListParams = {},
  ): Promise<SiteVisitListResponse> {
    const query = new URLSearchParams();

    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.page_size ?? 10));

    if (params.status) {
      query.set("status", params.status);
    }

    if (params.lead_id) {
      query.set("lead_id", params.lead_id);
    }

    if (params.customer_profile_id) {
      query.set("customer_profile_id", params.customer_profile_id);
    }

    if (params.property_id) {
      query.set("property_id", params.property_id);
    }

    return api.get<SiteVisitListResponse>(
      `/site-visits?${query.toString()}`,
    );
  },

  recordAttendance(
    siteVisitId: string,
    input: SiteVisitAttendanceInput,
  ): Promise<SiteVisit> {
    return api.patch<SiteVisit>(
      `/site-visits/${siteVisitId}/attendance`,
      input,
    );
  },
};
