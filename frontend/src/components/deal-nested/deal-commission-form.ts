import type { DealCommission, DealCommissionCreateInput, DealCommissionType, DealCommissionUpdateInput } from "../../services/dealApi";

/** Currencies offered in the form. A commission in another currency keeps its own code (see currencyOptions). */
export const COMMISSION_CURRENCIES = ["INR", "USD", "AED", "GBP"] as const;

export interface CommissionFormValues {
  commissionType: DealCommissionType;
  /** Percentage of the deal's expected value, or a fixed amount, depending on commissionType. */
  amount: string;
  currency: string;
  terms: string;
}

export type CommissionFormErrors = Partial<Record<keyof CommissionFormValues, string>>;

const FIXED_PATTERN = /^\d+(\.\d{1,2})?$/;
const RATE_PATTERN = /^\d+(\.\d{1,4})?$/;
const MAX_FIXED = 999_999_999_999_999;

export function emptyCommissionForm(currency: string): CommissionFormValues {
  return { commissionType: "PERCENTAGE", amount: "", currency: normalizeCurrency(currency), terms: "" };
}

export function commissionToForm(commission: DealCommission): CommissionFormValues {
  const isFixed = commission.commission_type === "FIXED";
  return {
    commissionType: commission.commission_type,
    amount: String((isFixed ? commission.fixed_amount : commission.rate_percent) ?? ""),
    currency: commission.currency,
    terms: commission.terms ?? "",
  };
}

export function currencyOptions(current: string): string[] {
  const code = normalizeCurrency(current);
  return (COMMISSION_CURRENCIES as readonly string[]).includes(code) ? [...COMMISSION_CURRENCIES] : [code, ...COMMISSION_CURRENCIES];
}

export function validateCommissionForm(values: CommissionFormValues): CommissionFormErrors {
  const errors: CommissionFormErrors = {};
  const amount = values.amount.trim();
  const isPercentage = values.commissionType === "PERCENTAGE";

  if (!amount) {
    errors.amount = isPercentage ? "Enter a commission percentage." : "Enter a commission amount.";
  } else if (isPercentage) {
    if (!RATE_PATTERN.test(amount)) errors.amount = "Enter a percentage with up to four decimal places.";
    else if (Number(amount) <= 0) errors.amount = "Commission percentage must be greater than zero.";
    else if (Number(amount) > 100) errors.amount = "Commission percentage cannot exceed 100%.";
  } else if (!FIXED_PATTERN.test(amount)) {
    errors.amount = "Enter an amount with up to two decimal places.";
  } else if (Number(amount) <= 0) {
    errors.amount = "Commission amount must be greater than zero.";
  } else if (Number(amount) > MAX_FIXED) {
    errors.amount = "Commission amount is too large.";
  }

  if (!/^[A-Z]{3}$/.test(normalizeCurrency(values.currency))) errors.currency = "Enter a valid three-letter currency code.";

  if (values.terms.trim().length > 10000) errors.terms = "Use 10000 characters or fewer.";

  return errors;
}

export function toCommissionCreateInput(values: CommissionFormValues): DealCommissionCreateInput {
  const amount = Number(values.amount.trim());
  const base = { currency: normalizeCurrency(values.currency), terms: values.terms.trim() || null };
  return values.commissionType === "FIXED"
    ? { commission_type: "FIXED", fixed_amount: amount, ...base }
    : { commission_type: "PERCENTAGE", rate_percent: amount, ...base };
}

export function toCommissionUpdateInput(values: CommissionFormValues): DealCommissionUpdateInput {
  const amount = Number(values.amount.trim());
  const isFixed = values.commissionType === "FIXED";
  return {
    commission_type: values.commissionType,
    fixed_amount: isFixed ? amount : null,
    rate_percent: isFixed ? null : amount,
    currency: normalizeCurrency(values.currency),
    terms: values.terms.trim() || null,
  };
}

export function isSameCommissionForm(a: CommissionFormValues, b: CommissionFormValues): boolean {
  return a.commissionType === b.commissionType && a.amount === b.amount && a.currency === b.currency && a.terms === b.terms;
}

export function normalizeCurrency(value: string): string {
  return value.trim().toUpperCase();
}

export function commissionDescription(commission: DealCommission): string {
  if (commission.commission_type === "PERCENTAGE") return "Percentage of deal value";
  return "Fixed amount";
}

export function commissionRateLabel(commission: DealCommission): string {
  if (commission.commission_type === "PERCENTAGE") {
    return commission.rate_percent === null ? "—" : `${Number(commission.rate_percent).toLocaleString("en-IN", { maximumFractionDigits: 4 })}%`;
  }
  return "—";
}

export function commissionStatus(commission: DealCommission): { label: string; tone: "pending" | "active" | "success" | "neutral" } {
  switch (commission.status) {
    case "PROPOSED":
      return { label: "Proposed", tone: "pending" };
    case "AGREED":
      return { label: "Agreed", tone: "active" };
    case "PAID":
      return { label: "Paid", tone: "success" };
    case "CANCELLED":
      return { label: "Cancelled", tone: "neutral" };
  }
}
