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

export type RunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "waiting_timer"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "stopped"
  | "timed_out"
  | "dead_letter";

export interface RunStep {
  step_id: string;
  step_index: number;
  type: StepType;
  status: string;
  attempts: number;
  reason_code: string | null;
  trace: Record<string, unknown> | null;
  wake_at: string | null;
  decided_at: string | null;
  finished_at: string | null;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: RunStatus;
  version_id: string;
  version_number: number;
  trigger: { type: "manual" | "event"; event: string | null; event_key: string | null; source_execution_id: string | null };
  retry_of_execution_id: string | null;
  run_as_user_id: string;
  initiated_by_user_id: string | null;
  failure_reason: string | null;
  steps_completed: number;
  next_step_id: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  deadline_at: string | null;
  output: Record<string, unknown> | null;
  steps?: RunStep[];
  pending_approval?: { step_id: string; approver_permission: string | null; reason: string | null } | null;
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
  startRun(workflowId: string, input: Record<string, unknown>, idempotencyKey: string) {
    return api.post<WorkflowRun & { created: boolean }>(`${BASE}/${encodeURIComponent(workflowId)}/executions`, {
      input,
      idempotency_key: idempotencyKey,
    });
  },
  listRuns(workflowId: string) {
    return api.get<{ items: WorkflowRun[] }>(`${BASE}/${encodeURIComponent(workflowId)}/executions`);
  },
  getRun(runId: string) {
    return api.get<WorkflowRun>(`/automation/executions/${encodeURIComponent(runId)}`);
  },
  cancelRun(runId: string) {
    return api.post<WorkflowRun>(`/automation/executions/${encodeURIComponent(runId)}/cancel`, {});
  },
  retryRun(runId: string) {
    return api.post<WorkflowRun & { created: boolean }>(`/automation/executions/${encodeURIComponent(runId)}/retry`, {});
  },
  decideStep(runId: string, stepId: string, decision: "approve" | "reject", reason?: string) {
    return api.post<WorkflowRun>(
      `/automation/executions/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}/decision`,
      { decision, reason },
    );
  },
};
