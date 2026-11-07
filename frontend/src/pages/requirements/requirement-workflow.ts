import type { CustomerRequirement, ParkingPreference, PossessionPreference, PropertyType } from "../../services/requirementApi";

export const REQUIREMENT_PROPERTY_TYPES: readonly PropertyType[] = ["APARTMENT", "VILLA", "INDEPENDENT_HOUSE", "PLOT", "COMMERCIAL", "OTHER"];
export const POSSESSION_OPTIONS: readonly PossessionPreference[] = [
  "READY_TO_MOVE",
  "WITHIN_3_MONTHS",
  "WITHIN_6_MONTHS",
  "WITHIN_12_MONTHS",
  "AFTER_12_MONTHS",
  "ANY",
];
export const PARKING_OPTIONS: readonly ParkingPreference[] = ["REQUIRED", "PREFERRED", "NOT_REQUIRED", "ANY"];

export function enumLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

export function formatBudget(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Not set";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(numeric);
}

/** Budget range for the grid and the record: a range when both ends are set, otherwise "From" or "Up to". */
export function budgetRange(item: Pick<CustomerRequirement, "budget_min" | "budget_max">): string {
  const hasMin = item.budget_min !== null && item.budget_min !== undefined && item.budget_min !== "";
  const hasMax = item.budget_max !== null && item.budget_max !== undefined && item.budget_max !== "";
  if (!hasMin && !hasMax) return "Not set";
  if (hasMin && hasMax) return `${formatBudget(item.budget_min)} to ${formatBudget(item.budget_max)}`;
  return hasMin ? `From ${formatBudget(item.budget_min)}` : `Up to ${formatBudget(item.budget_max)}`;
}

export function requirementCustomerName(item: Pick<CustomerRequirement, "customer_name">): string {
  return item.customer_name?.trim() || "Customer not assigned";
}

export function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/** Budget rules from the legacy Requirements page. Returns an error message, or null when valid. */
export function budgetError(minText: string, maxText: string): string | null {
  const minimum = optionalNumber(minText);
  const maximum = optionalNumber(maxText);
  if ((minText.trim() && minimum === null) || (maxText.trim() && maximum === null)) return "Enter valid budget amounts.";
  if ((minimum !== null && minimum < 0) || (maximum !== null && maximum < 0)) return "Budget cannot be negative.";
  if (minimum !== null && maximum !== null && minimum > maximum) return "Minimum budget cannot exceed maximum budget.";
  return null;
}

export function bhkError(minText: string, maxText: string): string | null {
  const minimum = optionalNumber(minText);
  const maximum = optionalNumber(maxText);
  if ((minText.trim() && (!Number.isInteger(minimum) || (minimum ?? 0) < 1)) || (maxText.trim() && (!Number.isInteger(maximum) || (maximum ?? 0) < 1))) {
    return "BHK values must be positive whole numbers.";
  }
  if (minimum !== null && maximum !== null && minimum > maximum) return "Minimum BHK cannot exceed maximum BHK.";
  return null;
}

export function parkingSpacesError(text: string): string | null {
  const spaces = optionalNumber(text);
  if (text.trim() && (!Number.isInteger(spaces) || (spaces ?? 0) < 1)) return "Minimum parking spaces must be a positive whole number.";
  return null;
}
