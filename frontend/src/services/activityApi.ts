
import { api } from "../lib/api";

export type ActivityType =
  | "NOTE"
  | "CALL"
  | "EMAIL"
  | "MEETING"
  | "STATUS_CHANGE"
  | "OWNER_CHANGE"
  | "TASK"
  | "OTHER";

export interface LeadActivity {
  id: string;
  organization_id: string;
  lead_id: string;
  actor_id: string;
  actor_display_name: string | null;
  activity_type: ActivityType;
  title: string;
  description: string | null;
  details: Record<string, unknown> | null;
  occurred_at: string;
  created_at: string;
}

export interface LeadActivityListResponse {
  items: LeadActivity[];
}

export const activityApi = {
  listForLead(leadId: string): Promise<LeadActivityListResponse> {
    return api.get<LeadActivityListResponse>(
      `/leads/${encodeURIComponent(leadId)}/activities`,
    );
  },
};
