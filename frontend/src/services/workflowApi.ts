import { api } from "../lib/api";

export type WorkflowStatus = "draft" | "published" | "paused" | "archived";
export type StepType = "crm_action" | "condition" | "agent" | "approval" | "delay";

export interface WorkflowProblem {
  path: string;
  message: string;
}

export interface WorkflowStep {
  id: string;
  type: StepType;
  next?: string | null;
  timeout_seconds?: number;
  retry?: { max_attempts: number; backoff_seconds: number };
  on_failure?: { policy: "stop" | "route"; route_to?: string | null };
  action?: string;
  arguments?: Record<string, string>;
  condition?: { left: string; operator: string; right?: unknown };
  then?: string;
  else?: string;
  agent_id?: string;
  approver_permission?: string;
  reason?: string;
  seconds?: number;
}

export interface WorkflowConfiguration {
  schema_version?: string;
  category?: string | null;
  purpose?: string | null;
  trigger?: { type: "manual" } | { type: "event"; event: string };
  inputs?: Array<{ name: string; type: string; required: boolean }>;
  entry?: string | null;
  steps?: WorkflowStep[];
  outputs?: Record<string, string>;
  limits?: Record<string, number>;
  metadata?: { labels: string[] };
}

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string | null;
  status: WorkflowStatus;
  revision: number;
  current_version_id: string | null;
  updated_at: string | null;
}

export interface WorkflowDetail extends WorkflowSummary {
  draft: WorkflowConfiguration;
  has_unpublished_changes: boolean;
  current_version: VersionSummary | null;
}

export interface VersionSummary {
  id: string;
  version_number: number;
  name: string;
  content_hash: string;
  schema_version: string;
  required_permissions: string[];
  agent_references: Array<{ step: string; agent_id: string; inputs: string[] }>;
  published_at: string | null;
  published_by_user_id: string;
}

export interface LifecycleEvent {
  action: string;
  from_status: string | null;
  to_status: string;
  version_id: string | null;
  target_version_id: string | null;
  actor_user_id: string;
  reason: string | null;
  created_at: string | null;
}

const BASE = "/automation/workflows";

export const workflowApi = {
  list() {
    return api.get<{ items: WorkflowSummary[] }>(BASE);
  },
  get(workflowId: string) {
    return api.get<WorkflowDetail>(`${BASE}/${encodeURIComponent(workflowId)}`);
  },
  create(input: { name: string; description?: string | null; configuration?: WorkflowConfiguration }) {
    return api.post<WorkflowDetail>(BASE, input);
  },
  saveDraft(
    workflowId: string,
    input: { revision: number; name?: string; description?: string | null; configuration?: WorkflowConfiguration },
  ) {
    return api.patch<WorkflowDetail>(`${BASE}/${encodeURIComponent(workflowId)}`, input);
  },
  validate(workflowId: string) {
    return api.post<{ valid: boolean; problems: WorkflowProblem[]; revision: number }>(
      `${BASE}/${encodeURIComponent(workflowId)}/validate`,
      {},
    );
  },
  publish(workflowId: string) {
    return api.post<VersionSummary & { created: boolean }>(`${BASE}/${encodeURIComponent(workflowId)}/publish`, {});
  },
  pause(workflowId: string, reason?: string) {
    return api.post<WorkflowDetail>(`${BASE}/${encodeURIComponent(workflowId)}/pause`, { reason });
  },
  resume(workflowId: string) {
    return api.post<WorkflowDetail>(`${BASE}/${encodeURIComponent(workflowId)}/resume`, {});
  },
  archive(workflowId: string) {
    return api.post<WorkflowDetail>(`${BASE}/${encodeURIComponent(workflowId)}/archive`, {});
  },
  rollback(workflowId: string, versionNumber: number) {
    return api.post<WorkflowDetail>(`${BASE}/${encodeURIComponent(workflowId)}/rollback`, {
      version_number: versionNumber,
    });
  },
  versions(workflowId: string) {
    return api.get<{ items: VersionSummary[] }>(`${BASE}/${encodeURIComponent(workflowId)}/versions`);
  },
  history(workflowId: string) {
    return api.get<{ items: LifecycleEvent[] }>(`${BASE}/${encodeURIComponent(workflowId)}/history`);
  },
};
