import { describe, expect, it } from "vitest";

import { NEGOTIATION_TRANSITIONS, NEXT_DEAL_STAGE, dealFieldsError, dealStageLabel, formatDealAmount, negotiationNeedsReason } from "./deal-workflow";

describe("deal stages and negotiation rules", () => {
  it("advances a deal along the normal path only", () => {
    expect(NEXT_DEAL_STAGE.NEW).toBe("QUALIFICATION");
    expect(NEXT_DEAL_STAGE.BOOKING).toBeUndefined();
    expect(dealStageLabel("CLOSED_WON")).toBe("Closed Won");
  });

  it("allows only the legacy negotiation moves from each state", () => {
    expect(NEGOTIATION_TRANSITIONS.COMPLETED).toEqual(["IN_PROGRESS"]);
    expect(NEGOTIATION_TRANSITIONS.IN_PROGRESS).toContain("TERMS_AGREED");
  });

  it("requires a reason for cancelling or reopening a negotiation", () => {
    expect(negotiationNeedsReason("IN_PROGRESS", "CANCELLED")).toBe(true);
    expect(negotiationNeedsReason("CANCELLED", "IN_PROGRESS")).toBe(true);
    expect(negotiationNeedsReason("IN_PROGRESS", "STALLED")).toBe(false);
  });
});

describe("deal field validation", () => {
  it("checks the currency code and a non-negative expected value", () => {
    expect(dealFieldsError("", "INR")).toBeNull();
    expect(dealFieldsError("100", "inr")).toBeNull();
    expect(dealFieldsError("100", "RUPEE")).toBe("Enter a valid three-letter currency code.");
    expect(dealFieldsError("-5", "INR")).toBe("Expected value must be zero or more.");
  });

  it("shows an unset value as Not set", () => {
    expect(formatDealAmount(null, "INR")).toBe("Not set");
    expect(formatDealAmount("abc", "INR")).toBe("Not set");
    expect(formatDealAmount("7500000", "INR")).toContain("75,00,000");
  });
});
