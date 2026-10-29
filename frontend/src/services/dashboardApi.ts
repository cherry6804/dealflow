import { api } from "../lib/api";

export interface PipelineValue {
  currency: string;
  total: string;
}

export interface DealSummary {
  by_stage: Record<string, number>;
  open_value_by_currency: PipelineValue[];
}

export interface FollowUpItem {
  id: string;
  title: string;
  follow_up_type: string;
  due_at: string;
  lead_id: string;
  contact_name: string;
  interest: string | null;
}

export interface FollowUpSummary {
  overdue_count: number;
  today_count: number;
  upcoming_count: number;
  overdue: FollowUpItem[];
  today: FollowUpItem[];
  upcoming: FollowUpItem[];
}

export interface LeadActionItem {
  lead_id: string;
  contact_name: string;
  action: string;
  due_at: string;
  status: string;
  interest: string | null;
}

export interface LeadActionSummary {
  overdue_count: number;
  today_count: number;
  overdue: LeadActionItem[];
  today: LeadActionItem[];
}

export interface DashboardAccess {
  deals: boolean;
  follow_ups: boolean;
  lead_actions: boolean;
}

export interface DashboardSummary {
  day_start: string;
  day_end: string;
  access: DashboardAccess;
  deals: DealSummary | null;
  follow_ups: FollowUpSummary | null;
  lead_actions: LeadActionSummary | null;
}

export const dashboardApi = {
  getSummary(dayStart: Date, dayEnd: Date): Promise<DashboardSummary> {
    const query = new URLSearchParams({
      day_start: dayStart.toISOString(),
      day_end: dayEnd.toISOString(),
    });

    return api.get<DashboardSummary>(`/dashboard/summary?${query.toString()}`);
  },
};
