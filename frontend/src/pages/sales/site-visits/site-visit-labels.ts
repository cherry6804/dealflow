import type { CustomerProfile } from "../../../services/customerProfileApi";
import type { Lead } from "../../../services/leadApi";
import type { Property } from "../../../services/propertyApi";
import type { SiteVisit, SiteVisitOutcome, SiteVisitStatus } from "../../../services/siteVisitApi";
import { personName } from "../sales-shared";

export const SITE_VISIT_STATUSES: readonly { value: SiteVisitStatus; label: string }[] = [
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "COMPLETED", label: "Completed" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "NO_SHOW", label: "No show" },
];

export const SITE_VISIT_OUTCOMES: readonly { value: SiteVisitOutcome; label: string }[] = [
  { value: "INTERESTED", label: "Interested" },
  { value: "NOT_INTERESTED", label: "Not interested" },
  { value: "NEGOTIATION", label: "Negotiation" },
  { value: "FOLLOW_UP_REQUIRED", label: "Follow-up required" },
  { value: "OTHER", label: "Other" },
];

export function siteVisitStatusLabel(status: SiteVisitStatus): string {
  return SITE_VISIT_STATUSES.find((item) => item.value === status)?.label ?? status;
}

export function siteVisitOutcomeLabel(outcome: SiteVisitOutcome | null): string {
  if (!outcome) return "—";
  return SITE_VISIT_OUTCOMES.find((item) => item.value === outcome)?.label ?? outcome;
}

export function propertyLabel(property: Property | undefined, fallbackId: string): string {
  if (!property) return `Property ${fallbackId.slice(0, 8)}`;
  const address = [property.address_line_1, property.address_line_2, property.locality, property.city].filter(Boolean).join(", ");
  return address || `Property ${property.id.slice(0, 8)}`;
}

/** Customer name when the visit is linked to a customer profile, otherwise the lead name. */
export function visitPersonLabel(visit: SiteVisit, leadById: Map<string, Lead>, customerById: Map<string, CustomerProfile>, contactNameOfLead: (lead: Lead) => string): string {
  if (visit.customer_profile_id) {
    const customer = customerById.get(visit.customer_profile_id);
    if (customer) return personName(customer.contact) || customer.contact.email || customer.contact.phone || "Unnamed customer";
    return "Customer unavailable";
  }
  if (visit.lead_id) {
    const lead = leadById.get(visit.lead_id);
    return lead ? contactNameOfLead(lead) : "Lead unavailable";
  }
  return "Not linked";
}

export function visitDateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return date.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Local datetime-local value for a date, rounded to the minute. */
export function toLocalInput(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}
