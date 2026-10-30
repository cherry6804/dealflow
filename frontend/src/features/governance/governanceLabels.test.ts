import { describe, expect, it } from "vitest";

import {
  capabilityLabel,
  formatUnitQuantity,
  reasonLabel,
  requestStatusLabel,
  retentionLabel,
  unitLabel,
} from "./governanceLabels";

describe("governance labels", () => {
  it("names every catalogue capability and falls back to the key", () => {
    expect(capabilityLabel("automation.master")).toBe("Automation (master switch)");
    expect(capabilityLabel("unknown.key")).toBe("unknown.key");
  });

  it("never shows an unrecognised denial reason as a permission", () => {
    expect(reasonLabel("provider_not_connected")).toBe("No verified provider connection");
    expect(reasonLabel("something_new")).toBe("Unavailable");
  });

  it("shows token counts as plain numbers, never as currency", () => {
    expect(formatUnitQuantity("tokens_output", 1234567)).toBe((1234567).toLocaleString());
    expect(formatUnitQuantity("tokens_output", 10)).not.toContain("₹");
  });

  it("shows audio milliseconds as seconds", () => {
    expect(formatUnitQuantity("audio_ms", 2500)).toMatch(/^2\.5/);
  });

  it("shows provider cost minor units as currency", () => {
    const text = formatUnitQuantity("provider_cost_minor", 12345, "INR");
    expect(text).toMatch(/123\.45/);
  });

  it("labels units and retention treatments explicitly", () => {
    expect(unitLabel("customer_credits")).toBe("Customer credits");
    expect(retentionLabel("mandatory_record")).toContain("not deleted on request");
  });

  it("states that a recorded deletion eligibility performs no deletion", () => {
    expect(requestStatusLabel("eligibility_recorded")).toContain("no deletion performed");
    expect(requestStatusLabel("awaiting_artifact_generation")).toBe("Awaiting export generation");
  });
});
