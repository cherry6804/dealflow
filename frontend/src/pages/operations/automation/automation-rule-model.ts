import type { AutomationExecution, AutomationExecutionStatus, AutomationRule, AutomationRuleInput, AutomationRuleStatus } from "../../../services/automationRuleApi";

/**
 * The automation rules the API supports. A rule starts when a deal is created, optionally checks conditions on that deal, and then
 * creates a follow-up. Nothing else is offered as a working control; other automation ideas are described as planned.
 */

export const TRIGGER_TYPE = "DEAL_CREATED";
export const ACTION_TYPE = "CREATE_FOLLOW_UP";
export const MAX_DAYS_AFTER = 3650;

export const FOLLOW_UP_TYPES = [
  { value: "CALL", label: "Phone call" },
  { value: "EMAIL", label: "Email" },
  { value: "MEETING", label: "Meeting" },
  { value: "VISIT", label: "Property visit" },
  { value: "TASK", label: "Task" },
  { value: "OTHER", label: "Other" },
] as const;

export const CONDITION_FIELDS = [
  { value: "stage", label: "Deal stage" },
  { value: "expected_value", label: "Expected deal value" },
  { value: "currency", label: "Currency" },
  { value: "owner_user_id", label: "Deal owner ID" },
  { value: "lead_id", label: "Lead ID" },
  { value: "customer_profile_id", label: "Customer profile ID" },
  { value: "property_id", label: "Property ID" },
  { value: "notes", label: "Deal notes" },
] as const;

export const CONDITION_OPERATORS = [
  { value: "equals", label: "Equals" },
  { value: "not_equals", label: "Does not equal" },
  { value: "in", label: "Is one of" },
  { value: "not_in", label: "Is not one of" },
  { value: "exists", label: "Has a value" },
] as const;

export type ConditionField = (typeof CONDITION_FIELDS)[number]["value"];
export type ConditionOperator = (typeof CONDITION_OPERATORS)[number]["value"];

export interface AutomationForm {
  name: string;
  description: string;
  useCondition: boolean;
  conditionField: ConditionField;
  conditionOperator: ConditionOperator;
  conditionValue: string;
  conditionExists: boolean;
  daysAfter: string;
  followUpTitle: string;
  followUpDescription: string;
  followUpType: string;
}

export type AutomationFormErrors = Partial<Record<"name" | "conditionValue" | "daysAfter" | "followUpTitle", string>>;

export interface RuleEditorData {
  form: AutomationForm;
  extraConditions: Array<Record<string, unknown>>;
  extraActions: Array<Record<string, unknown>>;
}

export function createEmptyForm(): AutomationForm {
  return {
    name: "",
    description: "",
    useCondition: false,
    conditionField: "stage",
    conditionOperator: "equals",
    conditionValue: "NEW",
    conditionExists: true,
    daysAfter: "1",
    followUpTitle: "Contact lead about new deal",
    followUpDescription: "",
    followUpType: "CALL",
  };
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getString(record: Record<string, unknown>, key: string, fallback = ""): string {
  const value = record[key];
  return typeof value === "string" ? value : fallback;
}

function getConditionValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Reads a saved rule into the editor's form. Only the first condition and action are editable; any others are kept as they are. */
export function getRuleEditorData(rule: AutomationRule): RuleEditorData {
  const firstCondition = isRecord(rule.conditions[0]) ? rule.conditions[0] : null;
  const firstAction = isRecord(rule.actions[0]) ? rule.actions[0] : null;
  const actionConfig = firstAction && isRecord(firstAction.config) ? firstAction.config : {};

  const rawField = firstCondition?.field;
  const conditionField = CONDITION_FIELDS.some((field) => field.value === rawField) ? (rawField as ConditionField) : "stage";

  const rawOperator = firstCondition?.operator;
  const conditionOperator = CONDITION_OPERATORS.some((operator) => operator.value === rawOperator) ? (rawOperator as ConditionOperator) : "equals";

  return {
    form: {
      name: rule.name,
      description: rule.description ?? "",
      useCondition: rule.conditions.length > 0,
      conditionField,
      conditionOperator,
      conditionValue: firstCondition && "value" in firstCondition ? getConditionValue(firstCondition.value) : "",
      conditionExists: firstCondition?.value === true,
      daysAfter: typeof actionConfig.days_after === "number" ? String(actionConfig.days_after) : "1",
      followUpTitle: getString(actionConfig, "title", "Contact lead about new deal"),
      followUpDescription: getString(actionConfig, "description"),
      followUpType: getString(actionConfig, "follow_up_type", "TASK"),
    },
    extraConditions: rule.conditions.slice(1),
    extraActions: rule.actions.slice(1),
  };
}

export function buildCondition(form: AutomationForm): Record<string, unknown> {
  let value: unknown;
  if (form.conditionOperator === "exists") {
    value = form.conditionExists;
  } else if (form.conditionOperator === "in" || form.conditionOperator === "not_in") {
    value = form.conditionValue
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  } else if (form.conditionField === "expected_value") {
    value = Number(form.conditionValue);
  } else {
    value = form.conditionValue.trim();
  }
  return { field: form.conditionField, operator: form.conditionOperator, value };
}

/** Checks the form before anything is sent, using the same limits the server applies. */
export function validateAutomationForm(form: AutomationForm): AutomationFormErrors {
  const errors: AutomationFormErrors = {};
  if (!form.name.trim()) errors.name = "Enter a name for this rule.";
  else if (form.name.trim().length > 150) errors.name = "Use 150 characters or fewer.";

  if (!form.followUpTitle.trim()) errors.followUpTitle = "Enter the title of the follow-up.";

  const days = form.daysAfter.trim();
  if (!/^\d+$/.test(days) || Number(days) < 0 || Number(days) > MAX_DAYS_AFTER) {
    errors.daysAfter = `Enter a whole number of days from 0 to ${MAX_DAYS_AFTER}.`;
  }

  if (form.useCondition && form.conditionOperator !== "exists") {
    if (!form.conditionValue.trim()) {
      errors.conditionValue = "Enter the value to compare with.";
    } else if (form.conditionField === "expected_value" && !Number.isFinite(Number(form.conditionValue))) {
      errors.conditionValue = "Enter a number for the expected deal value.";
    }
  }
  return errors;
}

export function isSameForm(a: AutomationForm, b: AutomationForm): boolean {
  return (Object.keys(a) as Array<keyof AutomationForm>).every((key) => a[key] === b[key]);
}

export function buildRuleInput(form: AutomationForm, extraConditions: Array<Record<string, unknown>>, extraActions: Array<Record<string, unknown>>): AutomationRuleInput {
  const conditions = form.useCondition ? [buildCondition(form), ...extraConditions] : [...extraConditions];
  const actions = [
    {
      type: ACTION_TYPE,
      config: {
        days_after: Number(form.daysAfter),
        title: form.followUpTitle.trim(),
        description: form.followUpDescription.trim() || null,
        follow_up_type: form.followUpType,
      },
    },
    ...extraActions,
  ];
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    trigger_type: TRIGGER_TYPE,
    trigger_config: { source: "deals" },
    conditions,
    actions,
  };
}

export function ruleStatusLabel(status: AutomationRuleStatus): string {
  switch (status) {
    case "DRAFT":
      return "Draft";
    case "ACTIVE":
      return "Active";
    case "DISABLED":
      return "Disabled";
  }
}

export function ruleStatusTone(status: AutomationRuleStatus): "success" | "pending" | "neutral" {
  if (status === "ACTIVE") return "success";
  if (status === "DRAFT") return "pending";
  return "neutral";
}

function fieldLabel(field: unknown): string {
  return CONDITION_FIELDS.find((item) => item.value === field)?.label ?? String(field ?? "Unknown field");
}

function operatorLabel(operator: unknown): string {
  return CONDITION_OPERATORS.find((item) => item.value === operator)?.label ?? String(operator ?? "");
}

export function describeCondition(condition: unknown): string {
  if (!isRecord(condition)) return "Unrecognised condition";
  if (condition.operator === "exists") {
    return `${fieldLabel(condition.field)} ${condition.value === false ? "is empty" : "has a value"}`;
  }
  return `${fieldLabel(condition.field)} ${operatorLabel(condition.operator).toLowerCase()} ${getConditionValue(condition.value)}`;
}

export interface RuleDescription {
  trigger: string;
  action: string;
  conditions: string[];
}

/** Plain-language summary of what a rule does, from its saved configuration. */
export function describeRule(rule: AutomationRule): RuleDescription {
  const firstAction = isRecord(rule.actions[0]) ? rule.actions[0] : null;
  const config = firstAction && isRecord(firstAction.config) ? firstAction.config : {};
  const days = typeof config.days_after === "number" ? config.days_after : null;
  const typeLabel = FOLLOW_UP_TYPES.find((item) => item.value === config.follow_up_type)?.label ?? "Task";
  return {
    trigger: rule.trigger_type === TRIGGER_TYPE ? "When a deal is created" : `When ${rule.trigger_type.toLowerCase().replace(/_/g, " ")}`,
    action:
      firstAction?.type === ACTION_TYPE
        ? `Create a ${typeLabel.toLowerCase()} follow-up${days === null ? "" : days === 0 ? " today" : ` in ${days} day${days === 1 ? "" : "s"}`}`
        : "No supported action",
    conditions: rule.conditions.map(describeCondition),
  };
}

export function eventTypeLabel(eventType: string): string {
  if (eventType === TRIGGER_TYPE) return "Deal created";
  return eventType.toLowerCase().replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

export function executionStatusLabel(status: AutomationExecutionStatus): string {
  switch (status) {
    case "PENDING":
      return "Waiting to run";
    case "RUNNING":
      return "Running";
    case "SUCCEEDED":
      return "Succeeded";
    case "PARTIAL":
      return "Partly succeeded";
    case "FAILED":
      return "Failed";
    case "SKIPPED":
      return "Skipped";
  }
}

export function executionStatusTone(status: AutomationExecutionStatus): "success" | "danger" | "pending" | "neutral" {
  switch (status) {
    case "SUCCEEDED":
      return "success";
    case "FAILED":
      return "danger";
    case "PARTIAL":
    case "PENDING":
    case "RUNNING":
      return "pending";
    case "SKIPPED":
      return "neutral";
  }
}

export interface ActionOutcome {
  type: string;
  label: string;
  succeeded: boolean | null;
  detail: string;
}

/**
 * Reads each action result the server recorded. Fields the server did not send are left out, never guessed.
 */
export function actionOutcomes(results: readonly unknown[]): ActionOutcome[] {
  return results.map((result) => {
    const record = isRecord(result) ? result : {};
    const type = typeof record.type === "string" ? record.type : "Unknown action";
    const status = typeof record.status === "string" ? record.status.toUpperCase() : typeof record.outcome === "string" ? record.outcome.toUpperCase() : "";
    const succeeded = status === "SUCCEEDED" || status === "SUCCESS" || status === "COMPLETED" ? true : status === "FAILED" || status === "ERROR" ? false : null;
    const message = typeof record.message === "string" ? record.message : typeof record.error === "string" ? record.error : typeof record.reason === "string" ? record.reason : "";
    return {
      type,
      label: type === ACTION_TYPE ? "Create follow-up" : type.toLowerCase().replace(/_/g, " "),
      succeeded,
      detail: message,
    };
  });
}

/** The reason an execution did not fully succeed, when the server recorded one. */
export function failureReason(execution: Pick<AutomationExecution, "status" | "error_message" | "action_results">): string | null {
  if (execution.error_message?.trim()) return execution.error_message;
  const failed = actionOutcomes(execution.action_results).find((item) => item.succeeded === false);
  if (failed) return failed.detail || `The ${failed.label.toLowerCase()} action did not complete.`;
  return null;
}

/** The API has no retry operation for automation runs. */
export const RETRY_UNAVAILABLE_NOTE =
  "Automation runs cannot be retried from here. A rule runs again only when a matching deal is created.";
