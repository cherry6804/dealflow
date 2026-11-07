import { describe, expect, it } from "vitest";

import type { DealCommission, PaymentMilestone } from "../../services/dealApi";
import { commissionStatus, currencyOptions as commissionCurrencies, validateCommissionForm, type CommissionFormValues } from "./deal-commission-form";
import {
  milestoneStatus,
  currencyOptions as milestoneCurrencies,
  milestoneToForm,
  toMilestoneCreateInput,
  validateMilestoneForm,
  type MilestoneFormValues,
} from "./payment-milestone-form";
import { formatMoney, totalsByCurrency } from "../record/nested-records";

const baseMilestone: PaymentMilestone = {
  id: "m1",
  organization_id: "o1",
  deal_id: "d1",
  name: "Booking advance",
  amount: "500000.00",
  currency: "INR",
  due_at: "2026-12-01T10:00:00+05:30",
  notes: null,
  status: "PENDING",
  paid_at: null,
  payment_reference: null,
  paid_by_user_id: null,
  created_by_user_id: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  is_overdue: false,
};

const validMilestone: MilestoneFormValues = { name: "Final payment", amount: "250000.5", currency: "INR", dueAt: "2026-12-15T09:30", notes: "" };

describe("payment milestone rules", () => {
  it("accepts a valid milestone and converts it to the API input", () => {
    expect(validateMilestoneForm(validMilestone)).toEqual({});
    const input = toMilestoneCreateInput(validMilestone);
    expect(input.amount).toBe(250000.5);
    expect(input.currency).toBe("INR");
    expect(input.notes).toBeNull();
    expect(new Date(input.due_at).toISOString()).toBe(input.due_at);
  });

  it("rejects blank names, zero or malformed amounts, bad currency and missing dates", () => {
    const errors = validateMilestoneForm({ name: "   ", amount: "0", currency: "RUPEE", dueAt: "", notes: "" });
    expect(errors.name).toBe("Enter a milestone name.");
    expect(errors.amount).toBe("Amount must be greater than zero.");
    expect(errors.currency).toBe("Enter a valid three-letter currency code.");
    expect(errors.dueAt).toBe("Select a valid due date and time.");
    expect(validateMilestoneForm({ ...validMilestone, amount: "10.555" }).amount).toBe("Enter an amount with up to two decimal places.");
    expect(validateMilestoneForm({ ...validMilestone, amount: "-5" }).amount).toBe("Enter an amount with up to two decimal places.");
  });

  it("shows overdue only from the API flag on a pending milestone", () => {
    expect(milestoneStatus({ ...baseMilestone, is_overdue: true })).toEqual({ label: "Overdue", tone: "danger" });
    expect(milestoneStatus(baseMilestone)).toEqual({ label: "Pending", tone: "pending" });
    expect(milestoneStatus({ ...baseMilestone, status: "PAID", is_overdue: true }).label).toBe("Paid");
    expect(milestoneStatus({ ...baseMilestone, status: "CANCELLED" }).label).toBe("Cancelled");
  });

  it("keeps a milestone's own currency selectable even when it is not in the default list", () => {
    expect(milestoneCurrencies("EUR")).toEqual(["EUR", "INR", "USD", "AED", "GBP"]);
    expect(milestoneCurrencies("INR")).toEqual(["INR", "USD", "AED", "GBP"]);
  });

  it("round-trips an existing milestone into the edit form", () => {
    const form = milestoneToForm(baseMilestone);
    expect(form.name).toBe("Booking advance");
    expect(form.amount).toBe("500000.00");
    expect(form.dueAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });
});

const baseCommission: DealCommission = {
  id: "c1",
  organization_id: "o1",
  deal_id: "d1",
  commission_type: "PERCENTAGE",
  fixed_amount: null,
  rate_percent: "2.5",
  currency: "INR",
  status: "PROPOSED",
  terms: null,
  agreed_at: null,
  paid_at: null,
  payment_reference: null,
  created_by_user_id: null,
  updated_by_user_id: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  calculated_amount: "12500.00",
};

const validCommission: CommissionFormValues = { commissionType: "PERCENTAGE", amount: "2.5", currency: "INR", terms: "" };

describe("commission rules", () => {
  it("validates percentage and fixed amounts against the backend limits", () => {
    expect(validateCommissionForm(validCommission)).toEqual({});
    expect(validateCommissionForm({ ...validCommission, amount: "101" }).amount).toBe("Commission percentage cannot exceed 100%.");
    expect(validateCommissionForm({ ...validCommission, amount: "0" }).amount).toBe("Commission percentage must be greater than zero.");
    expect(validateCommissionForm({ ...validCommission, amount: "1.23456" }).amount).toBe("Enter a percentage with up to four decimal places.");
    expect(validateCommissionForm({ commissionType: "FIXED", amount: "50000.5", currency: "INR", terms: "" })).toEqual({});
    expect(validateCommissionForm({ commissionType: "FIXED", amount: "0", currency: "INR", terms: "" }).amount).toBe(
      "Commission amount must be greater than zero.",
    );
  });

  it("keeps a commission's own currency selectable", () => {
    expect(commissionCurrencies("EUR")[0]).toBe("EUR");
  });

  it("maps statuses to the labels the backend defines", () => {
    expect(commissionStatus(baseCommission)).toEqual({ label: "Proposed", tone: "pending" });
    expect(commissionStatus({ ...baseCommission, status: "AGREED" }).label).toBe("Agreed");
    expect(commissionStatus({ ...baseCommission, status: "PAID" }).label).toBe("Paid");
    expect(commissionStatus({ ...baseCommission, status: "CANCELLED" }).label).toBe("Cancelled");
  });
});

describe("money totals", () => {
  it("adds in minor units, so decimal amounts do not drift", () => {
    const totals = totalsByCurrency([
      { amount: "0.10", currency: "INR" },
      { amount: "0.20", currency: "INR" },
      { amount: "0.30", currency: "INR" },
    ]);
    expect(totals).toEqual([{ currency: "INR", total: 0.6, unavailable: 0, count: 3 }]);
  });

  it("never adds different currencies together", () => {
    const totals = totalsByCurrency([
      { amount: "1000", currency: "USD" },
      { amount: "500", currency: "INR" },
    ]);
    expect(totals.map((item) => item.currency)).toEqual(["INR", "USD"]);
  });

  it("counts rows without an amount instead of treating them as zero", () => {
    const totals = totalsByCurrency([
      { amount: "12500", currency: "INR" },
      { amount: null, currency: "INR" },
    ]);
    expect(totals).toEqual([{ currency: "INR", total: 12500, unavailable: 1, count: 2 }]);
  });

  it("formats a missing amount as not available, never as zero", () => {
    expect(formatMoney(null, "INR")).toBe("Not available");
    expect(formatMoney("", "INR")).toBe("Not available");
    expect(formatMoney("abc", "INR")).toBe("Not available");
    expect(formatMoney("1000", "INR")).toContain("1,000");
  });
});
