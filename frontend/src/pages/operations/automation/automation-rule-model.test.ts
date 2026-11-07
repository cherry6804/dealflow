import { describe, expect, it } from "vitest";

import type { AutomationExecution, AutomationRule } from "../../../services/automationRuleApi";
import {
  actionOutcomes,
  buildRuleInput,
  createEmptyForm,
  describeRule,
  eventTypeLabel,
  failureReason,
  getRuleEditorData,
  validateAutomationForm,
} from "./automation-rule-model";

function rule(overrides: Partial<AutomationRule> = {}): AutomationRule {
  return {
    id: "r1",
    organization_id: "o1",
    name: "Follow up new deals",
    description: null,
    trigger_type: "DEAL_CREATED",
    trigger_config: { source: "deals" },
    conditions: [],
    actions: [{ type: "CREATE_FOLLOW_UP", config: { days_after: 2, title: "Call the buyer", follow_up_type: "CALL" } }],
    status: "DRAFT",
    created_by_user_id: null,
    updated_by_user_id: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-02T00:00:00Z",
    ...overrides,
  };
}

function execution(overrides: Partial<AutomationExecution> = {}): AutomationExecution {
  return {
    id: "e1",
    organization_id: "o1",
    rule_id: "r1",
    event_type: "DEAL_CREATED",
    event_id: "d1",
    status: "FAILED",
    action_results: [],
    error_message: null,
    started_at: "2026-11-03T10:00:00Z",
    completed_at: "2026-11-03T10:00:01Z",
    created_at: "2026-11-03T10:00:00Z",
    updated_at: "2026-11-03T10:00:01Z",
    ...overrides,
  };
}

describe("automation rule form", () => {
  it("validates the name, the delay and the follow-up title against the server limits", () => {
    const empty = { ...createEmptyForm(), name: " " };
    expect(validateAutomationForm(empty).name).toBe("Enter a name for this rule.");
    expect(validateAutomationForm({ ...createEmptyForm(), name: "Rule", daysAfter: "3650" })).toEqual({});
    expect(validateAutomationForm({ ...createEmptyForm(), name: "Rule", daysAfter: "3651" }).daysAfter).toContain("0 to 3650");
    expect(validateAutomationForm({ ...createEmptyForm(), name: "Rule", daysAfter: "1.5" }).daysAfter).toBeDefined();
    expect(validateAutomationForm({ ...createEmptyForm(), name: "Rule", followUpTitle: "" }).followUpTitle).toBeDefined();
  });

  it("requires a numeric value for an expected-value condition", () => {
    const form = {
      ...createEmptyForm(),
      name: "Rule",
      useCondition: true,
      conditionField: "expected_value" as const,
      conditionOperator: "equals" as const,
      conditionValue: "lots",
    };
    expect(validateAutomationForm(form).conditionValue).toBe("Enter a number for the expected deal value.");
  });

  it("builds the same payload the server accepts, and keeps extra conditions and actions", () => {
    const form = { ...createEmptyForm(), name: "Stage follow-up", useCondition: true, conditionField: "stage" as const, conditionValue: "NEW", daysAfter: "0" };
    const input = buildRuleInput(form, [{ field: "currency", operator: "equals", value: "INR" }], [{ type: "CREATE_FOLLOW_UP", config: { days_after: 5, title: "Second" } }]);
    expect(input.trigger_type).toBe("DEAL_CREATED");
    expect(input.trigger_config).toEqual({ source: "deals" });
    expect(input.conditions).toEqual([
      { field: "stage", operator: "equals", value: "NEW" },
      { field: "currency", operator: "equals", value: "INR" },
    ]);
    expect(input.actions[0]).toMatchObject({ type: "CREATE_FOLLOW_UP", config: { days_after: 0, title: "Contact lead about new deal" } });
    expect(input.actions[1]).toEqual({ type: "CREATE_FOLLOW_UP", config: { days_after: 5, title: "Second" } });
  });

  it("reads a saved rule back into the editor without losing its configuration", () => {
    const data = getRuleEditorData(rule({ conditions: [{ field: "expected_value", operator: "not_equals", value: 1000 }] }));
    expect(data.form.daysAfter).toBe("2");
    expect(data.form.followUpType).toBe("CALL");
    expect(data.form.useCondition).toBe(true);
    expect(data.form.conditionField).toBe("expected_value");
    expect(data.form.conditionValue).toBe("1000");
  });
});

describe("automation descriptions", () => {
  it("describes what a rule does in plain language", () => {
    const description = describeRule(rule({ conditions: [{ field: "stage", operator: "equals", value: "NEW" }] }));
    expect(description.trigger).toBe("When a deal is created");
    expect(description.action).toBe("Create a phone call follow-up in 2 days");
    expect(description.conditions).toEqual(["Deal stage equals NEW"]);
  });

  it("says when a follow-up is due the same day, and never claims an unsupported action", () => {
    expect(describeRule(rule({ actions: [{ type: "CREATE_FOLLOW_UP", config: { days_after: 0, follow_up_type: "TASK" } }] })).action).toBe(
      "Create a task follow-up today",
    );
    expect(describeRule(rule({ actions: [{ type: "SEND_EMAIL", config: {} }] })).action).toBe("No supported action");
  });

  it("names the trigger the run was for", () => {
    expect(eventTypeLabel("DEAL_CREATED")).toBe("Deal created");
    expect(eventTypeLabel("LEAD_UPDATED")).toBe("Lead updated");
  });
});

describe("automation outcomes", () => {
  it("shows the reason for a failed run when the server recorded one", () => {
    expect(failureReason(execution({ error_message: "The follow-up could not be created." }))).toBe("The follow-up could not be created.");
    expect(
      failureReason(
        execution({ action_results: [{ type: "CREATE_FOLLOW_UP", status: "FAILED", message: "Lead is closed." }] }),
      ),
    ).toBe("Lead is closed.");
  });

  it("returns no reason when none was recorded, rather than inventing one", () => {
    expect(failureReason(execution({ error_message: null, action_results: [] }))).toBeNull();
    expect(failureReason(execution({ status: "SUCCEEDED" }))).toBeNull();
  });

  it("reports each action's outcome as succeeded, failed, or no result", () => {
    const outcomes = actionOutcomes([
      { type: "CREATE_FOLLOW_UP", status: "SUCCEEDED" },
      { type: "CREATE_FOLLOW_UP", status: "FAILED", message: "Nope" },
      { type: "CREATE_FOLLOW_UP" },
    ]);
    expect(outcomes.map((item) => item.succeeded)).toEqual([true, false, null]);
    expect(outcomes[1].detail).toBe("Nope");
  });
});
