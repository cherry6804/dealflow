import type { PaymentMilestone, PaymentMilestoneCreateInput, PaymentMilestoneUpdateInput } from "../../services/dealApi";

/** Currencies offered in the form. A record in another currency keeps its own code (see currencyOptions). */
export const MILESTONE_CURRENCIES = ["INR", "USD", "AED", "GBP"] as const;

export interface MilestoneFormValues {
  name: string;
  amount: string;
  currency: string;
  /** Local date and time from a datetime-local input, for example 2026-11-20T10:30. */
  dueAt: string;
  notes: string;
}

export type MilestoneFormErrors = Partial<Record<keyof MilestoneFormValues, string>>;

const MAX_AMOUNT = 999_999_999_999_999;
const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;

export function emptyMilestoneForm(currency: string): MilestoneFormValues {
  return { name: "", amount: "", currency: normalizeCurrency(currency), dueAt: "", notes: "" };
}

export function milestoneToForm(milestone: PaymentMilestone): MilestoneFormValues {
  return {
    name: milestone.name,
    amount: String(milestone.amount),
    currency: milestone.currency,
    dueAt: toLocalDateTimeInput(milestone.due_at),
    notes: milestone.notes ?? "",
  };
}

export function currencyOptions(current: string): string[] {
  const code = normalizeCurrency(current);
  return (MILESTONE_CURRENCIES as readonly string[]).includes(code) ? [...MILESTONE_CURRENCIES] : [code, ...MILESTONE_CURRENCIES];
}

export function validateMilestoneForm(values: MilestoneFormValues): MilestoneFormErrors {
  const errors: MilestoneFormErrors = {};
  const name = values.name.trim();
  const amount = values.amount.trim();

  if (!name) errors.name = "Enter a milestone name.";
  else if (name.length > 150) errors.name = "Use 150 characters or fewer.";

  if (!amount) {
    errors.amount = "Enter an amount.";
  } else if (!AMOUNT_PATTERN.test(amount)) {
    errors.amount = "Enter an amount with up to two decimal places.";
  } else if (Number(amount) <= 0) {
    errors.amount = "Amount must be greater than zero.";
  } else if (Number(amount) > MAX_AMOUNT) {
    errors.amount = "Amount is too large.";
  }

  if (!/^[A-Z]{3}$/.test(normalizeCurrency(values.currency))) errors.currency = "Enter a valid three-letter currency code.";

  if (!values.dueAt || Number.isNaN(new Date(values.dueAt).getTime())) errors.dueAt = "Select a valid due date and time.";

  if (values.notes.trim().length > 2000) errors.notes = "Use 2000 characters or fewer.";

  return errors;
}

export function toMilestoneCreateInput(values: MilestoneFormValues): PaymentMilestoneCreateInput {
  return {
    name: values.name.trim(),
    amount: Number(values.amount.trim()),
    currency: normalizeCurrency(values.currency),
    due_at: new Date(values.dueAt).toISOString(),
    notes: values.notes.trim() || null,
  };
}

export function toMilestoneUpdateInput(values: MilestoneFormValues): PaymentMilestoneUpdateInput {
  return toMilestoneCreateInput(values);
}

export function isSameMilestoneForm(a: MilestoneFormValues, b: MilestoneFormValues): boolean {
  return a.name === b.name && a.amount === b.amount && a.currency === b.currency && a.dueAt === b.dueAt && a.notes === b.notes;
}

export function normalizeCurrency(value: string): string {
  return value.trim().toUpperCase();
}

/** Converts an API timestamp into the value a datetime-local input expects, in the user's local time. */
export function toLocalDateTimeInput(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

/** Milestone status as the user sees it. Overdue comes from the API's own is_overdue flag, never from the browser clock. */
export function milestoneStatus(milestone: PaymentMilestone): { label: string; tone: "pending" | "danger" | "success" | "neutral" } {
  if (milestone.status === "PAID") return { label: "Paid", tone: "success" };
  if (milestone.status === "CANCELLED") return { label: "Cancelled", tone: "neutral" };
  return milestone.is_overdue ? { label: "Overdue", tone: "danger" } : { label: "Pending", tone: "pending" };
}
