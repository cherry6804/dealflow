import { api } from "../lib/api";

export type FollowUpType =
  | "CALL"
  | "EMAIL"
  | "MEETING"
  | "VISIT"
  | "TASK"
  | "OTHER";

export type FollowUpStatus = "PENDING" | "COMPLETED" | "CANCELLED";

export interface FollowUp {
  id: string;
  organization_id: string;
  lead_id: string;
  owner_user_id: string;
  follow_up_type: FollowUpType;
  title: string;
  description: string | null;
  due_at: string;
  status: FollowUpStatus;
  completed_at: string | null;
  completed_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FollowUpCreateInput {
  follow_up_type: FollowUpType;
  title: string;
  description?: string | null;
  due_at: string;
  owner_user_id?: string | null;
}

export interface FollowUpRescheduleInput {
  due_at: string;
}


export interface BulkFollowUpRequest {
  follow_up_ids: string[];
}

export interface BulkFollowUpRescheduleInput extends BulkFollowUpRequest {
  due_at: string;
}

export interface BulkFollowUpItemResult {
  follow_up_id: string;
  success: boolean;
  message: string;
  follow_up?: FollowUp | null;
}

export interface BulkFollowUpResponse {
  total: number;
  succeeded: number;
  failed: number;
  results: BulkFollowUpItemResult[];
}


export interface FollowUpListParams {
  due_before?: string;
  overdue_only?: boolean;
}

function buildQuery(params: FollowUpListParams = {}): string {
  const query = new URLSearchParams();

  if (params.due_before) {
    query.set("due_before", params.due_before);
  }

  if (params.overdue_only !== undefined) {
    query.set("overdue_only", String(params.overdue_only));
  }

  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export const followUpsApi = {
  list(params: FollowUpListParams = {}): Promise<FollowUp[]> {
    return api.get<FollowUp[]>(`/follow-ups${buildQuery(params)}`);
  },

  create(
    leadId: string,
    input: FollowUpCreateInput,
  ): Promise<FollowUp> {
    return api.post<FollowUp>(
      `/leads/${encodeURIComponent(leadId)}/follow-ups`,
      input,
    );
  },

  complete(followUpId: string): Promise<FollowUp> {
    return api.post<FollowUp>(
      `/follow-ups/${encodeURIComponent(followUpId)}/complete`,
      {},
    );
  },

  reschedule(
    followUpId: string,
    input: FollowUpRescheduleInput,
  ): Promise<FollowUp> {
    return api.patch<FollowUp>(
      `/follow-ups/${encodeURIComponent(followUpId)}/reschedule`,
      input,
    );
  },


  bulkComplete(
    input: BulkFollowUpRequest,
  ): Promise<BulkFollowUpResponse> {
    return api.post<BulkFollowUpResponse>(
      "/follow-ups/bulk-complete",
      input,
    );
  },

  bulkReschedule(
    input: BulkFollowUpRescheduleInput,
  ): Promise<BulkFollowUpResponse> {
    return api.post<BulkFollowUpResponse>(
      "/follow-ups/bulk-reschedule",
      input,
    );
  },

};
