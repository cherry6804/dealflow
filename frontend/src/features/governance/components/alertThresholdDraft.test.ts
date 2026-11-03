import { describe, expect, it } from "vitest";

import { parseThresholdDraft } from "./alertThresholdDraft";

describe("parseThresholdDraft", () => {
  it("accepts strictly increasing whole numbers that end at 100", () => {
    expect(parseThresholdDraft(["70", "85", "100"])).toEqual({ ok: true, values: [70, 85, 100] });
    expect(parseThresholdDraft([" 1 ", "2", "100"])).toEqual({ ok: true, values: [1, 2, 100] });
  });

  it("refuses a value that is not a whole number", () => {
    for (const draft of ["", "70.5", "-1", "seventy", "7e1"]) {
      const result = parseThresholdDraft([draft, "85", "100"]);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error).toBe("Each alert threshold must be a whole number.");
    }
  });

  it("refuses a value outside 1 to 100", () => {
    for (const draft of ["0", "101", "999"]) {
      const result = parseThresholdDraft([draft, "85", "100"]);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error).toBe("Each alert threshold must be from 1 to 100.");
    }
  });

  it("refuses duplicates and values that do not increase", () => {
    for (const drafts of [
      ["70", "70", "100"],
      ["85", "70", "100"],
      ["70", "100", "85"],
    ]) {
      const result = parseThresholdDraft(drafts);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error).toBe("Alert thresholds must increase, with no duplicates.");
    }
  });

  it("refuses a final alert that is not 100", () => {
    const result = parseThresholdDraft(["70", "85", "99"]);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("The highest alert threshold must be 100.");
  });

  it("refuses anything other than three values", () => {
    const result = parseThresholdDraft(["70", "100"]);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("Enter exactly three alert thresholds.");
  });
});
