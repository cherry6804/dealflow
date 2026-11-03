import { describe, expect, it } from "vitest";

import {
  capabilityLabel,
  describePrivacyExecution,
  formatUnitQuantity,
  privacyReasonLabel,
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

  it("explains every execution gate reason the server can return", () => {
    for (const code of ["entitlement_not_defined", "approval_not_available", "budget_gate_not_available", "actor_required", "membership_inactive", "resource_not_active"]) {
      expect(reasonLabel(code)).not.toBe("Unavailable");
    }
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
    expect(requestStatusLabel("ready_partial")).toContain("incomplete");
    expect(requestStatusLabel("partially_completed")).toContain("not deleted");
  });

  it("explains each category that an export or deletion did not cover", () => {
    const lines = describePrivacyExecution({
      not_exported: [{ category_key: "messaging.email_outbox", reason: "not_organization_owned" }],
      "crm.contacts": { outcome: "anonymized_partial", count: 2 },
      "crm.leads": { outcome: "not_executed", reasons: ["deletion_executor_not_built"] },
    });
    expect(lines).toContain(
      "messaging.email_outbox: not exported (Platform data, not organization data)",
    );
    expect(lines).toContain("crm.contacts: Identity fields anonymized; linked records kept");
    expect(lines).toContain("crm.leads: Not processed (Deletion not available yet)");
  });

  it("never shows an unknown privacy reason as an allowed action", () => {
    expect(privacyReasonLabel("something_new")).toBe("Not available");
  });
});
