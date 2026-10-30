
import { api } from "../lib/api";

export type AutomationRuleStatus = "DRAFT" | "ACTIVE" | "DISABLED";

export type AutomationExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "PARTIAL"
  | "FAILED"
  | "SKIPPED";

export interface AutomationRule {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  conditions: Array<Record<string, unknown>>;
  actions: Array<Record<string, unknown>>;
  status: AutomationRuleStatus;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationRuleInput {
  name: string;
  description?: string | null;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  conditions: Array<Record<string, unknown>>;
  actions: Array<Record<string, unknown>>;
}

export interface AutomationRuleListResponse {
  items: AutomationRule[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface AutomationRuleListParams {
  page?: number;
  page_size?: number;
  status?: AutomationRuleStatus;
}

export interface AutomationExecution {
  id: string;
  organization_id: string;
  rule_id: string;
  event_type: string;
  event_id: string;
  status: AutomationExecutionStatus;
  action_results: unknown[];
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationExecutionListParams {
  page?: number;
  page_size?: number;
  status?: AutomationExecutionStatus;
  rule_id?: string;
  event_type?: string;
}

export interface AutomationExecutionListResponse {
  items: AutomationExecution[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

function buildRuleQuery(params: AutomationRuleListParams = {}): string {
  const query = new URLSearchParams();

  if (params.page !== undefined) {
    query.set("page", String(params.page));
  }

  if (params.page_size !== undefined) {
    query.set("page_size", String(params.page_size));
  }

  if (params.status) {
    query.set("status", params.status);
  }

  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

function buildExecutionQuery(
  params: AutomationExecutionListParams = {},
): string {
  const query = new URLSearchParams();

  if (params.page !== undefined) {
    query.set("page", String(params.page));
  }

  if (params.page_size !== undefined) {
    query.set("page_size", String(params.page_size));
  }

  if (params.status) {
    query.set("status", params.status);
  }

  if (params.rule_id?.trim()) {
    query.set("rule_id", params.rule_id.trim());
  }

  if (params.event_type?.trim()) {
    query.set("event_type", params.event_type.trim());
  }

  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

const BASE_PATH = "/automation-rules";

export const automationRulesApi = {
  list(
    params: AutomationRuleListParams = {},
  ): Promise<AutomationRuleListResponse> {
    return api.get<AutomationRuleListResponse>(
      `${BASE_PATH}${buildRuleQuery(params)}`,
    );
  },

  get(ruleId: string): Promise<AutomationRule> {
    return api.get<AutomationRule>(
      `${BASE_PATH}/${encodeURIComponent(ruleId)}`,
    );
  },

  create(input: AutomationRuleInput): Promise<AutomationRule> {
    return api.post<AutomationRule>(BASE_PATH, input);
  },

  update(
    ruleId: string,
    input: Partial<AutomationRuleInput>,
  ): Promise<AutomationRule> {
    return api.patch<AutomationRule>(
      `${BASE_PATH}/${encodeURIComponent(ruleId)}`,
      input,
    );
  },

  activate(ruleId: string): Promise<AutomationRule> {
    return api.post<AutomationRule>(
      `${BASE_PATH}/${encodeURIComponent(ruleId)}/activate`,
      {},
    );
  },

  disable(ruleId: string): Promise<AutomationRule> {
    return api.post<AutomationRule>(
      `${BASE_PATH}/${encodeURIComponent(ruleId)}/disable`,
      {},
    );
  },

  listExecutions(
    params: AutomationExecutionListParams = {},
  ): Promise<AutomationExecutionListResponse> {
    return api.get<AutomationExecutionListResponse>(
      `${BASE_PATH}/executions${buildExecutionQuery(params)}`,
    );
  },
};
