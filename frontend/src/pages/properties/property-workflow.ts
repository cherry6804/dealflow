import type { Property, PropertyStatus, PropertyTransactionType, PropertyType } from "../../services/propertyApi";

export const PROPERTY_TYPES: readonly PropertyType[] = ["APARTMENT", "VILLA", "INDEPENDENT_HOUSE", "PLOT", "COMMERCIAL", "OTHER"];
export const TRANSACTION_TYPES: readonly PropertyTransactionType[] = ["SALE", "RENT", "LEASE"];
export const PROPERTY_STATUSES: readonly PropertyStatus[] = ["AVAILABLE", "RESERVED", "SOLD", "RENTED", "LEASED", "UNAVAILABLE"];
export const CURRENCIES = ["INR", "USD", "AED", "GBP"] as const;

export function enumLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

export function formatAmount(value: number | string | null, currency: string | null = "INR"): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: currency || "INR", maximumFractionDigits: 0 }).format(numeric);
  } catch {
    return `${currency ?? "INR"} ${numeric.toLocaleString("en-IN")}`;
  }
}

/** Headline price for a listing: a monthly rent for rent, and the sale price otherwise. */
export function propertyPriceLabel(property: Property): string {
  const currency = property.currency || "INR";
  if (property.transaction_type === "RENT") return `${formatAmount(property.rent, currency)}/month`;
  if (property.transaction_type === "LEASE" && property.rent !== null) return `${formatAmount(property.rent, currency)}/month`;
  return formatAmount(property.price, currency);
}

export function propertyTitle(property: Property): string {
  const type = property.property_type ? enumLabel(property.property_type) : "Property";
  return property.bhk ? `${property.bhk} BHK ${type}` : type;
}

export function propertyAddress(property: Property): string {
  return [property.address_line_1, property.address_line_2, property.locality, property.city, property.state, property.postal_code]
    .filter(Boolean)
    .join(", ");
}

export function propertyLocation(property: Property): string {
  return [property.locality, property.city].filter(Boolean).join(", ") || "—";
}

export type PropertyStatusTone = "success" | "active" | "pending" | "danger" | "neutral";

/** Tone for an availability badge: available is positive, reserved is pending, closed deals are neutral. */
export function propertyStatusTone(status: PropertyStatus | null): PropertyStatusTone {
  switch (status) {
    case "AVAILABLE":
      return "success";
    case "RESERVED":
      return "pending";
    case "SOLD":
    case "RENTED":
    case "LEASED":
      return "active";
    case "UNAVAILABLE":
      return "danger";
    default:
      return "neutral";
  }
}

export interface PropertyForm {
  transaction_type: PropertyTransactionType;
  price: string;
  currency: string;
  rent: string;
  security_deposit: string;
  maintenance_charge: string;
  address_line_1: string;
  address_line_2: string;
  locality: string;
  city: string;
  state: string;
  postal_code: string;
  property_type: PropertyType;
  bhk: string;
  built_up_area: string;
  carpet_area: string;
  floor_number: string;
  total_floors: string;
  status: PropertyStatus;
}

export const EMPTY_PROPERTY_FORM: PropertyForm = {
  transaction_type: "SALE",
  price: "",
  currency: "INR",
  rent: "",
  security_deposit: "",
  maintenance_charge: "",
  address_line_1: "",
  address_line_2: "",
  locality: "",
  city: "",
  state: "",
  postal_code: "",
  property_type: "APARTMENT",
  bhk: "",
  built_up_area: "",
  carpet_area: "",
  floor_number: "",
  total_floors: "",
  status: "AVAILABLE",
};

export type PropertyFormErrors = Partial<Record<keyof PropertyForm, string>>;

/** Same rules the legacy Properties page enforces before it creates anything. */
export function validatePropertyForm(form: PropertyForm): PropertyFormErrors {
  const errors: PropertyFormErrors = {};
  if (!form.address_line_1.trim()) errors.address_line_1 = "Enter the first address line.";
  if (!form.locality.trim()) errors.locality = "Enter the locality.";
  if (!form.city.trim()) errors.city = "Enter the city.";
  if (!form.state.trim()) errors.state = "Enter the state.";
  if (form.transaction_type === "SALE" && !form.price.trim()) errors.price = "Enter the sale price.";
  if (form.transaction_type !== "SALE" && !form.rent.trim()) errors.rent = "Enter the monthly rent.";
  if (form.floor_number.trim() && form.total_floors.trim() && Number(form.floor_number) > Number(form.total_floors)) {
    errors.floor_number = "Floor number cannot be greater than total floors.";
  }
  return errors;
}

export function numericOrNull(value: string): number | null {
  if (!value.trim()) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function textOrNull(value: string): string | null {
  return value.trim() || null;
}
