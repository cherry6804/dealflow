import { api } from "../lib/api";

export type AgentStatus = "draft" | "published" | "paused" | "archived";

export type ExecutionStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "succeeded"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "stopped";

export interface ApprovedTool {
  key: string;
  description: string;
  required_permission: string;
  parameters: Array<{ name: string; type: string; required: boolean }>;
}

export interface AgentLimits {
  max_duration_seconds?: number;
  max_steps?: number;
  max_tool_calls?: number;
  max_retries?: number;
  max_output_characters?: number;
  max_concurrent_executions?: number;
  max_executions_per_hour?: number;
}

export interface AgentConfiguration {
  category?: string | null;
  purpose?: string | null;
  instructions?: string | null;
  language?: string;
  autonomy_level?: string;
  approval_policy?: string;
  tools?: string[];
  knowledge_document_ids?: string[];
  inputs?: Array<{ name: string; type: string; required: boolean }>;
  steps?: Array<Record<string, unknown>>;
  limits?: AgentLimits;
  [key: string]: unknown;
}

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  status: AgentStatus;
  owner_user_id: string;
  created_by_user_id: string;
  current_version_number: number | null;
  draft_configuration: AgentConfiguration;
  created_at: string;
  updated_at: string;
}

export interface AgentVersion {
  id: string;
  version_number: number;
  configuration: AgentConfiguration;
  validation_snapshot: Record<string, unknown>;
  published_by_user_id: string;
  published_at: string;
}

export interface ExecutionStep {
  index: number;
  kind: string;
  status: string;
  reason_code: string | null;
  attempts: number;
  trace: Record<string, unknown> | null;
  started_at: string;
  finished_at: string | null;
}

export interface AgentExecution {
  id: string;
  agent_id: string;
  agent_version_id: string;
  status: ExecutionStatus;
  failure_reason: string | null;
  initiated_by_user_id: string;
  correlation_id: string;
  steps_completed: number;
  tool_calls: number;
  model_calls: number;
  output: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  deadline_at: string | null;
  cancel_requested: boolean;
  created_at: string;
  steps?: ExecutionStep[];
  created?: boolean;
}

export interface PreviewResult {
  side_effects: boolean;
  publishable: boolean;
  problems: string[];
  plan: Array<Record<string, unknown>>;
  limits: AgentLimits;
}

export interface AgentWriteInput {
  name: string;
  description?: string | null;
  configuration: AgentConfiguration;
}

const BASE = "/agents";

export interface AgentTemplateSummary {
  key: string;
  title: string;
  purpose: string;
  tools: string[];
  steps: number;
}

export interface AgentExecutionMetrics {
  agent_id: string;
  total: number;
  by_status: Partial<Record<ExecutionStatus, number>>;
  failure_reasons: Array<{ reason: string; count: number }>;
}

export const agentApi = {
  templates() {
    return api.get<{ items: AgentTemplateSummary[] }>(`${BASE}/templates`);
  },
  createFromTemplate(input: { template_key: string; name: string; description?: string }) {
    return api.post<Agent>(`${BASE}/from-template`, input);
  },
  metrics(agentId: string) {
    return api.get<AgentExecutionMetrics>(`${BASE}/${encodeURIComponent(agentId)}/metrics`);
  },
  tools(): Promise<{ items: ApprovedTool[] }> {
    return api.get<{ items: ApprovedTool[] }>(`${BASE}/tools`);
  },
  list(): Promise<{ items: Agent[] }> {
    return api.get<{ items: Agent[] }>(BASE);
  },
  get(agentId: string): Promise<Agent> {
    return api.get<Agent>(`${BASE}/${encodeURIComponent(agentId)}`);
  },
  create(input: AgentWriteInput): Promise<Agent> {
    return api.post<Agent>(BASE, input);
  },
  update(agentId: string, input: Partial<AgentWriteInput>): Promise<Agent> {
    return api.patch<Agent>(`${BASE}/${encodeURIComponent(agentId)}`, input);
  },
  preview(agentId: string): Promise<PreviewResult> {
    return api.post<PreviewResult>(`${BASE}/${encodeURIComponent(agentId)}/preview`, {});
  },
  publish(agentId: string): Promise<AgentVersion> {
    return api.post<AgentVersion>(`${BASE}/${encodeURIComponent(agentId)}/publish`, {});
  },
  pause(agentId: string): Promise<Agent> {
    return api.post<Agent>(`${BASE}/${encodeURIComponent(agentId)}/pause`, {});
  },
  resume(agentId: string): Promise<Agent> {
    return api.post<Agent>(`${BASE}/${encodeURIComponent(agentId)}/resume`, {});
  },
  archive(agentId: string): Promise<Agent> {
    return api.post<Agent>(`${BASE}/${encodeURIComponent(agentId)}/archive`, {});
  },
  rollback(agentId: string, versionNumber: number): Promise<Agent> {
    return api.post<Agent>(`${BASE}/${encodeURIComponent(agentId)}/rollback`, {
      version_number: versionNumber,
    });
  },
  versions(agentId: string): Promise<{ items: AgentVersion[] }> {
    return api.get<{ items: AgentVersion[] }>(`${BASE}/${encodeURIComponent(agentId)}/versions`);
  },
  executions(agentId: string): Promise<{ items: AgentExecution[] }> {
    return api.get<{ items: AgentExecution[] }>(`${BASE}/${encodeURIComponent(agentId)}/executions`);
  },
  execution(executionId: string): Promise<AgentExecution> {
    return api.get<AgentExecution>(`${BASE}/executions/${encodeURIComponent(executionId)}`);
  },
  startExecution(agentId: string, input: Record<string, unknown>, idempotencyKey: string): Promise<AgentExecution> {
    return api.post<AgentExecution>(`${BASE}/${encodeURIComponent(agentId)}/executions`, {
      input,
      idempotency_key: idempotencyKey,
    });
  },
  cancelExecution(executionId: string): Promise<AgentExecution> {
    return api.post<AgentExecution>(`${BASE}/executions/${encodeURIComponent(executionId)}/cancel`, {});
  },
  decideApproval(executionId: string, stepIndex: number, approve: boolean): Promise<AgentExecution> {
    return api.post<AgentExecution>(
      `${BASE}/executions/${encodeURIComponent(executionId)}/steps/${stepIndex}/decision`,
      { approve },
    );
  },
};
