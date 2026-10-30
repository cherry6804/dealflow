import { ApiError } from "../../lib/api";

export interface SibvoEntitlement {
  feature_key: string;
  enabled: boolean;
  limit_value: number | null;
  limit_unit: string | null;
}

export interface SibvoAccess {
  subscription_status: string | null;
  plan_version_id: string | null;
  product_role: string | null;
  entitlements: SibvoEntitlement[];
}

/** Seat capacity as SIBVO reports it. Nothing here is computed in Dealsflo. */
export interface SibvoSeats {
  seat_limit: number | null;
  allocated: number;
  reserved: number;
  available: number | null;
  unlimited: boolean;
}

export type SeatState = "hidden" | "loading" | "ready" | "denied" | "unavailable";

const STATUS_TEXT: Record<string, string> = {
  trialing: "Free trial",
  active: "Active subscription",
  past_due: "Payment overdue. Access continues during the grace period.",
};

export function subscriptionStatusText(status: string | null): string {
  if (!status) {
    return "Unknown";
  }
  return STATUS_TEXT[status] ?? status;
}

export function accessErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "Plan details are available after you sign in through SIBVO.";
    }
    if (error.status === 401 || error.status === 403) {
      return "Your access to Dealsflo has ended. Sign in through SIBVO again to continue.";
    }
  }
  return "Plan details could not be loaded. Please try again.";
}

/** A 403 means SIBVO denied seat details for this session. Anything else is an outage. */
export function seatErrorState(error: unknown): SeatState {
  if (error instanceof ApiError && error.status === 403) {
    return "denied";
  }
  return "unavailable";
}

export interface SeatSummary {
  inUse: number;
  pending: number;
  limitLabel: string;
  availableLabel: string;
  atLimit: boolean;
}

export function summarizeSeats(seats: SibvoSeats): SeatSummary {
  const atLimit = !seats.unlimited && seats.available === 0;
  return {
    inUse: seats.allocated,
    pending: seats.reserved,
    limitLabel: seats.unlimited || seats.seat_limit === null ? "Unlimited" : String(seats.seat_limit),
    availableLabel:
      seats.unlimited || seats.available === null ? "Unlimited" : String(seats.available),
    atLimit,
  };
}

export function formatEntitlement(item: SibvoEntitlement): string {
  const name = item.feature_key.replace(/_/g, " ");
  if (item.limit_value === null) {
    return name;
  }
  const unit = item.limit_unit ? ` ${item.limit_unit}` : "";
  return `${name} (up to ${item.limit_value}${unit})`;
}
