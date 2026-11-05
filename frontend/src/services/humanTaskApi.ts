import { api } from "../lib/api";

export type HumanTaskStatus = "pending" | "approved" | "rejected" | "cancelled" | "expired";

export interface HumanTaskEvent {
  id: string;
  event_type: string;
  actor_user_id: string | null;
  from_user_id: string | null;
  to_user_id: string | null;
  comment: string | null;
  created_at: string | null;
}

export interface HumanTask {
  id: string;
  kind: "approval";
  status: HumanTaskStatus;
  title: string;
  instructions: string | null;
  required_permission: string;
  assigned_to_user_id: string | null;
  requested_by_user_id: string;
  decided_by_user_id: string | null;
  decided_at: string | null;
  decision_comment: string | null;
  due_at: string | null;
  version: number;
  workflow_execution_id: string | null;
  workflow_step_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface HumanTaskDetail extends HumanTask {
  events: HumanTaskEvent[];
}

export interface HumanTaskDecision extends HumanTask {
  changed: boolean;
}

const BASE = "/human-tasks";

export const humanTaskApi = {
  list(status?: HumanTaskStatus) {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return api.get<{ items: HumanTask[] }>(`${BASE}${query}`);
  },

  get(taskId: string) {
    return api.get<HumanTaskDetail>(`${BASE}/${encodeURIComponent(taskId)}`);
  },

  decide(taskId: string, decision: "approve" | "reject", comment: string | null) {
    return api.post<HumanTaskDecision>(`${BASE}/${encodeURIComponent(taskId)}/decision`, {
      decision,
      comment: comment?.trim() ? comment.trim() : null,
    });
  },

  comment(taskId: string, text: string) {
    return api.post<HumanTaskDetail>(`${BASE}/${encodeURIComponent(taskId)}/comments`, { text });
  },

  cancel(taskId: string, reason: string | null) {
    return api.post<HumanTask>(`${BASE}/${encodeURIComponent(taskId)}/cancel`, { reason });
  },
};
