import type { Contact } from "../../services/contactApi";
import type { CustomerProfile } from "../../services/customerProfileApi";
import type { Lead } from "../../services/leadApi";
import type { Property } from "../../services/propertyApi";
import { personName } from "../sales/sales-shared";
import type { DealStage, NegotiationState } from "../../services/dealApi";

export const DEAL_STAGES: readonly DealStage[] = ["NEW", "QUALIFICATION", "NEGOTIATION", "BOOKING", "CLOSED_WON", "CLOSED_LOST"];

/** The next stage a deal can advance to by the normal path. Closing as won or lost is a separate, reasoned action. */
export const NEXT_DEAL_STAGE: Partial<Record<DealStage, DealStage>> = {
  NEW: "QUALIFICATION",
  QUALIFICATION: "NEGOTIATION",
  NEGOTIATION: "BOOKING",
};

export const NEGOTIATION_TRANSITIONS: Record<NegotiationState, NegotiationState[]> = {
  IN_PROGRESS: ["WAITING_ON_CUSTOMER", "WAITING_ON_SELLER", "TERMS_AGREED", "STALLED", "CANCELLED"],
  WAITING_ON_CUSTOMER: ["IN_PROGRESS", "WAITING_ON_SELLER", "TERMS_AGREED", "STALLED", "CANCELLED"],
  WAITING_ON_SELLER: ["IN_PROGRESS", "WAITING_ON_CUSTOMER", "TERMS_AGREED", "STALLED", "CANCELLED"],
  STALLED: ["IN_PROGRESS", "WAITING_ON_CUSTOMER", "WAITING_ON_SELLER", "TERMS_AGREED", "CANCELLED"],
  TERMS_AGREED: ["IN_PROGRESS", "COMPLETED", "CANCELLED"],
  COMPLETED: ["IN_PROGRESS"],
  CANCELLED: ["IN_PROGRESS"],
};

/** Reopening or cancelling a negotiation needs a reason, as the legacy page requires. */
export function negotiationNeedsReason(current: NegotiationState, target: NegotiationState): boolean {
  if (target === "CANCELLED") return true;
  return target === "IN_PROGRESS" && (current === "COMPLETED" || current === "CANCELLED" || current === "TERMS_AGREED");
}

export const NEGOTIATION_NOTES: Record<NegotiationState, string[]> = {
  IN_PROGRESS: ["Initial discussion started", "Negotiation discussion resumed", "New offer received", "Counteroffer discussed", "Terms under discussion"],
  WAITING_ON_CUSTOMER: ["Customer reviewing the offer", "Waiting for customer response", "Customer requested more time", "Waiting for customer documents"],
  WAITING_ON_SELLER: ["Offer shared with seller", "Waiting for seller approval", "Seller reviewing the offer", "Waiting for revised seller price"],
  TERMS_AGREED: ["Price agreed", "Commercial terms agreed", "Final terms confirmed", "Documentation pending"],
  STALLED: ["Price mismatch", "Customer not responding", "Seller not responding", "Budget or financing concern", "Decision postponed"],
  COMPLETED: ["Negotiation successfully concluded", "Terms finalized for handover"],
  CANCELLED: ["Customer withdrew interest", "Price expectations could not be aligned", "Seller withdrew the property", "Customer selected another property"],
};

export function dealStageLabel(stage: string): string {
  return stage
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

export type DealStageTone = "neutral" | "active" | "pending" | "success" | "danger";

export function dealStageTone(stage: string): DealStageTone {
  switch (stage) {
    case "CLOSED_WON":
      return "success";
    case "CLOSED_LOST":
      return "danger";
    case "BOOKING":
      return "pending";
    case "NEGOTIATION":
    case "QUALIFICATION":
      return "active";
    default:
      return "neutral";
  }
}

export function formatDealAmount(value: number | string | null, currency: string | null): string {
  if (value === null || value === undefined || value === "") return "Not set";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "Not set";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: currency || "INR", maximumFractionDigits: 0 }).format(numeric);
  } catch {
    return `${currency ?? "INR"} ${numeric.toLocaleString("en-IN")}`;
  }
}

/** Rules for the deal's own fields, from the legacy Deals page. Returns an error message, or null. */
export function dealFieldsError(expectedValue: string, currency: string): string | null {
  if (!/^[A-Z]{3}$/.test(currency.trim().toUpperCase())) return "Enter a valid three-letter currency code.";
  if (expectedValue.trim()) {
    const value = Number(expectedValue);
    if (!Number.isFinite(value) || value < 0) return "Expected value must be zero or more.";
  }
  return null;
}

export function expectedValueOrNull(text: string): number | null {
  return text.trim() ? Number(text) : null;
}

export function leadOptionLabel(lead: Lead, contacts: readonly Contact[]): string {
  const contact = contacts.find((item) => item.id === lead.contact_id);
  const name = contact ? personName(contact) || "Unnamed contact" : "Contact unavailable";
  return `${name} · ${dealStageLabel(lead.status)}`;
}

export function dealPropertyTitle(property: Property | undefined): string {
  if (!property) return "Property unavailable";
  const address = [property.address_line_1, property.locality, property.city].filter(Boolean).join(", ");
  return address || `Property ${property.id.slice(0, 8)}`;
}


export function dealCustomerName(customer: CustomerProfile | undefined): string {
  return customer ? personName(customer.contact) || customer.contact.email || "Unnamed customer" : "Customer unavailable";
}
