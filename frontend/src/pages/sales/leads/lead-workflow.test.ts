import { describe, expect, it } from "vitest";

import { ALLOWED_STATUS_TRANSITIONS, availableStatuses, needsNextActionPrompt, outcomeForStatusChange } from "./lead-workflow";

describe("lead stage rules", () => {
  it("offers only the current stage and its allowed next stages", () => {
    expect(availableStatuses("NEW")).toEqual(["NEW", "CONTACTED", "QUALIFIED", "ON_HOLD"]);
    expect(availableStatuses("WON")).toEqual(["WON"]);
  });

  it("sets the outcome for won and lost, and clears it when a closed lead reopens", () => {
    expect(outcomeForStatusChange("NEGOTIATION", "WON")).toBe("SUCCESSFUL");
    expect(outcomeForStatusChange("NEGOTIATION", "LOST")).toBe("UNSUCCESSFUL");
    expect(outcomeForStatusChange("LOST", "ON_HOLD")).toBeNull();
    expect(outcomeForStatusChange("NEW", "CONTACTED")).toBeUndefined();
  });

  it("asks for a next action only for an active lead with none moving into a key stage", () => {
    const lead = { status: "NEW" as const, is_active: true, next_action: null };
    expect(needsNextActionPrompt(lead, "QUALIFIED")).toBe(true);
    expect(needsNextActionPrompt(lead, "ON_HOLD")).toBe(false);
    expect(needsNextActionPrompt({ ...lead, next_action: "Call back" }, "QUALIFIED")).toBe(false);
    expect(needsNextActionPrompt({ ...lead, is_active: false }, "QUALIFIED")).toBe(false);
  });

  it("keeps the transition table closed for won and lost leads", () => {
    expect(ALLOWED_STATUS_TRANSITIONS.WON).toEqual([]);
    expect(ALLOWED_STATUS_TRANSITIONS.LOST).toEqual([]);
  });
});
