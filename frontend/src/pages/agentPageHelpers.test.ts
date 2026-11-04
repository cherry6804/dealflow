import { describe, expect, it } from "vitest";

import {
  buildAgentInput,
  canCancel,
  describeFailure,
  emptyForm,
  formFromConfiguration,
  isTerminal,
  parseIdList,
  statusTone,
} from "./agentPageHelpers";

const DOC = "0b8b6f3a-2c1d-4e5f-8a9b-1c2d3e4f5a6b";

describe("buildAgentInput", () => {
  it("requires a name", () => {
    expect(() => buildAgentInput({ ...emptyForm(), name: "   " })).toThrow("A name is required.");
  });

  it("builds a manual-trigger configuration with the form's limits", () => {
    const input = buildAgentInput({ ...emptyForm(), name: "Qualifier", tools: ["contacts.get"] });
    expect(input.name).toBe("Qualifier");
    expect(input.configuration.trigger).toEqual({ type: "manual" });
    expect(input.configuration.tools).toEqual(["contacts.get"]);
    expect(input.configuration.limits).toMatchObject({ max_steps: 5, max_tool_calls: 2 });
  });

  it("rejects a limit outside its bounds before the server is asked", () => {
    const form = emptyForm();
    form.limits.max_steps = "99";
    expect(() => buildAgentInput({ ...form, name: "x" })).toThrow("Maximum steps must be a whole number from 1 to 20.");
  });

  it("rejects a plan that is not a JSON array", () => {
    expect(() => buildAgentInput({ ...emptyForm(), name: "x", stepsJson: "{}" })).toThrow("Plan must be a JSON array.");
    expect(() => buildAgentInput({ ...emptyForm(), name: "x", stepsJson: "[" })).toThrow("Plan must be valid JSON.");
  });
});

describe("parseIdList", () => {
  it("accepts identifiers separated by commas or spaces and removes repeats", () => {
    expect(parseIdList(`${DOC}, ${DOC}  ${DOC}`)).toEqual([DOC]);
  });

  it("refuses text that is not an identifier", () => {
    expect(() => parseIdList("guide.pdf")).toThrow("Knowledge sources must be document identifiers");
  });

  it("returns an empty list for blank input", () => {
    expect(parseIdList("  ")).toEqual([]);
  });
});

describe("formFromConfiguration", () => {
  it("loads a stored configuration back so an edit starts from what is saved", () => {
    const form = formFromConfiguration("Saved", "About", {
      category: "research",
      purpose: "Find facts",
      instructions: "Be brief",
      autonomy_level: "act",
      approval_policy: "none",
      tools: ["leads.get"],
      knowledge_document_ids: [DOC],
      limits: { max_steps: 3 },
      steps: [{ kind: "approval", reason: "Check" }],
    });
    expect(form.category).toBe("research");
    expect(form.autonomyLevel).toBe("act");
    expect(form.knowledgeIds).toBe(DOC);
    expect(form.limits.max_steps).toBe("3");
    expect(JSON.parse(form.stepsJson)).toEqual([{ kind: "approval", reason: "Check" }]);
  });
});

describe("execution state helpers", () => {
  it("treats only finished states as terminal", () => {
    expect(isTerminal("succeeded")).toBe(true);
    expect(isTerminal("stopped")).toBe(true);
    expect(isTerminal("waiting_approval")).toBe(false);
    expect(isTerminal("running")).toBe(false);
  });

  it("allows cancelling only while work is still pending", () => {
    expect(canCancel("queued")).toBe(true);
    expect(canCancel("waiting_approval")).toBe(true);
    expect(canCancel("failed")).toBe(false);
  });

  it("explains known stop reasons and shows unknown ones as they are", () => {
    expect(describeFailure("membership_revoked")).toContain("no longer belongs");
    expect(describeFailure("some_new_reason")).toBe("Stopped: some new reason.");
    expect(describeFailure(null)).toBeNull();
  });

  it("maps statuses to a tone", () => {
    expect(statusTone("published")).toBe("success");
    expect(statusTone("timed_out")).toBe("danger");
    expect(statusTone("paused")).toBe("warning");
    expect(statusTone("unknown")).toBe("neutral");
  });
});
