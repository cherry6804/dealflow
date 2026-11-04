import type {
  AgentConfiguration,
  AgentLimits,
  AgentWriteInput,
  ExecutionStatus,
} from "../services/agentApi";

export const LIMIT_FIELDS: Array<{ key: keyof AgentLimits; label: string; min: number; max: number }> = [
  { key: "max_duration_seconds", label: "Maximum duration (seconds)", min: 1, max: 300 },
  { key: "max_steps", label: "Maximum steps", min: 1, max: 20 },
  { key: "max_tool_calls", label: "Maximum tool calls", min: 0, max: 10 },
  { key: "max_retries", label: "Maximum retries per model step", min: 0, max: 2 },
  { key: "max_output_characters", label: "Maximum output size (characters)", min: 1, max: 16384 },
  { key: "max_concurrent_executions", label: "Maximum concurrent executions", min: 1, max: 5 },
  { key: "max_executions_per_hour", label: "Executions per hour", min: 1, max: 1000 },
];

export const CATEGORY_OPTIONS = ["sales", "operations", "research"] as const;
export const LANGUAGE_OPTIONS = ["en", "de", "es", "fr", "nl", "sv", "da", "nb"] as const;

export interface AgentForm {
  name: string;
  description: string;
  category: string;
  purpose: string;
  instructions: string;
  language: string;
  autonomyLevel: "suggest" | "act";
  approvalPolicy: "none" | "before_result";
  tools: string[];
  knowledgeIds: string;
  inputsJson: string;
  stepsJson: string;
  limits: Record<keyof AgentLimits, string>;
}

export function emptyForm(): AgentForm {
  return {
    name: "",
    description: "",
    category: "sales",
    purpose: "",
    instructions: "",
    language: "en",
    autonomyLevel: "suggest",
    approvalPolicy: "before_result",
    tools: [],
    knowledgeIds: "",
    inputsJson: "[]",
    stepsJson: "[]",
    limits: {
      max_duration_seconds: "60",
      max_steps: "5",
      max_tool_calls: "2",
      max_retries: "1",
      max_output_characters: "4000",
      max_concurrent_executions: "1",
      max_executions_per_hour: "20",
    },
  };
}

export function parseJsonArray(text: string, label: string): unknown[] {
  let value: unknown;
  try {
    value = JSON.parse(text.trim() === "" ? "[]" : text);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be a JSON array.`);
  }
  return value;
}

export function parseIdList(text: string): string[] {
  const items = text
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  for (const item of items) {
    if (!uuid.test(item)) {
      throw new Error("Knowledge sources must be document identifiers separated by commas or spaces.");
    }
  }
  return Array.from(new Set(items));
}

function parseLimits(raw: Record<keyof AgentLimits, string>): AgentLimits {
  const limits: AgentLimits = {};
  for (const field of LIMIT_FIELDS) {
    const text = raw[field.key].trim();
    if (text === "") {
      continue;
    }
    const value = Number(text);
    if (!Number.isInteger(value) || value < field.min || value > field.max) {
      throw new Error(`${field.label} must be a whole number from ${field.min} to ${field.max}.`);
    }
    limits[field.key] = value;
  }
  return limits;
}

/** Turn the form into the configuration the server validates. Only shape and bounds are checked here; the server decides. */
export function buildAgentInput(form: AgentForm): AgentWriteInput {
  const name = form.name.trim();
  if (name === "") {
    throw new Error("A name is required.");
  }
  const steps = parseJsonArray(form.stepsJson, "Plan");
  const inputs = parseJsonArray(form.inputsJson, "Inputs");
  const configuration: AgentConfiguration = {
    category: form.category,
    purpose: form.purpose.trim() || null,
    instructions: form.instructions.trim() || null,
    language: form.language,
    autonomy_level: form.autonomyLevel,
    approval_policy: form.approvalPolicy,
    trigger: { type: "manual" },
    tools: form.tools,
    knowledge_document_ids: parseIdList(form.knowledgeIds),
    inputs: inputs as AgentConfiguration["inputs"],
    steps: steps as AgentConfiguration["steps"],
    limits: parseLimits(form.limits),
  };
  return {
    name,
    description: form.description.trim() || null,
    configuration,
  };
}

/** Load a stored configuration back into the form, so an edit starts from what is saved. */
export function formFromConfiguration(name: string, description: string | null, config: AgentConfiguration): AgentForm {
  const base = emptyForm();
  const limits = { ...base.limits };
  for (const field of LIMIT_FIELDS) {
    const value = config.limits?.[field.key];
    if (value !== undefined) {
      limits[field.key] = String(value);
    }
  }
  return {
    ...base,
    name,
    description: description ?? "",
    category: config.category ?? base.category,
    purpose: config.purpose ?? "",
    instructions: config.instructions ?? "",
    language: config.language ?? base.language,
    autonomyLevel: config.autonomy_level === "act" ? "act" : "suggest",
    approvalPolicy: config.approval_policy === "before_result" ? "before_result" : "none",
    tools: [...(config.tools ?? [])],
    knowledgeIds: (config.knowledge_document_ids ?? []).join(", "),
    inputsJson: JSON.stringify(config.inputs ?? [], null, 2),
    stepsJson: JSON.stringify(config.steps ?? [], null, 2),
    limits,
  };
}

export const TERMINAL_EXECUTION_STATUSES: ReadonlyArray<ExecutionStatus> = [
  "succeeded",
  "failed",
  "timed_out",
  "cancelled",
  "stopped",
];

export function isTerminal(status: ExecutionStatus): boolean {
  return TERMINAL_EXECUTION_STATUSES.includes(status);
}

export function canCancel(status: ExecutionStatus): boolean {
  return status === "queued" || status === "running" || status === "waiting_approval";
}

const REASON_TEXT: Record<string, string> = {
  deadline_exceeded: "The execution ran past its maximum duration and was stopped.",
  membership_revoked: "The member who started this run no longer belongs to the organization. The run stopped.",
  permission_removed: "The member who started this run no longer has permission to run agents. The run stopped.",
  permission_denied: "The member who started this run lacks permission for a step. The run stopped.",
  tool_permission_denied: "The member who started this run lacks permission for a tool step. The run stopped.",
  agent_paused: "The agent was paused while this run was in progress. The run stopped before its next step.",
  agent_archived: "The agent was archived while this run was in progress. The run stopped before its next step.",
  budget_exhausted: "The organization's AI budget could not cover this step. The run stopped.",
  budget_not_configured: "No AI budget is configured for the organization. The run stopped.",
  provider_unavailable: "The AI provider was unavailable after the allowed retries.",
  provider_timeout: "The AI provider did not answer in time after the allowed retries.",
  invalid_structured_output: "The model's answer did not match the required output format.",
  output_too_large: "The result was larger than the agent's output limit.",
  tool_call_limit: "The run reached its tool-call limit.",
  step_limit: "The run reached its step limit.",
  approval_rejected: "A reviewer rejected this run.",
  interrupted_step: "A step was interrupted before it finished, so the run stopped rather than repeat it.",
  cancel_requested: "The run was cancelled.",
};

/** A plain explanation for a stable failure reason. Unknown reasons are shown as they are, never guessed at. */
export function describeFailure(reason: string | null): string | null {
  if (reason === null) {
    return null;
  }
  return REASON_TEXT[reason] ?? `Stopped: ${reason.replace(/_/g, " ")}.`;
}

export function statusTone(status: string): "neutral" | "info" | "success" | "warning" | "danger" {
  switch (status) {
    case "succeeded":
    case "published":
      return "success";
    case "queued":
    case "running":
    case "draft":
      return "info";
    case "waiting_approval":
    case "paused":
      return "warning";
    case "failed":
    case "timed_out":
    case "stopped":
      return "danger";
    default:
      return "neutral";
  }
}
