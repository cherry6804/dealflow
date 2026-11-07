import type { LeadInterest, LeadOutcome, LeadStatus } from "../../../services/leadApi";

/** Lead stages in pipeline order. The same list the legacy Leads page uses. */
export const LEAD_STATUSES: readonly LeadStatus[] = [
  "NEW",
  "CONTACTED",
  "QUALIFIED",
  "MATCHING",
  "VISIT",
  "NEGOTIATION",
  "WON",
  "LOST",
  "ON_HOLD",
];

/** Stage moves allowed from each stage, as the existing Leads page enforces them. */
export const ALLOWED_STATUS_TRANSITIONS: Readonly<Record<LeadStatus, readonly LeadStatus[]>> = {
  NEW: ["CONTACTED", "QUALIFIED", "ON_HOLD"],
  CONTACTED: ["QUALIFIED", "MATCHING", "ON_HOLD"],
  QUALIFIED: ["MATCHING", "VISIT", "ON_HOLD"],
  MATCHING: ["VISIT", "QUALIFIED", "ON_HOLD"],
  VISIT: ["MATCHING", "NEGOTIATION", "QUALIFIED", "ON_HOLD"],
  NEGOTIATION: ["WON", "LOST", "VISIT", "ON_HOLD"],
  WON: [],
  LOST: [],
  ON_HOLD: ["CONTACTED", "QUALIFIED", "MATCHING", "VISIT", "NEGOTIATION"],
};

/** Moving an active lead into one of these stages asks for a next action when it has none. */
export const NEXT_ACTION_REQUIRED_STATUSES: readonly LeadStatus[] = ["CONTACTED", "QUALIFIED", "MATCHING", "VISIT", "NEGOTIATION"];

export const LEAD_INTERESTS: readonly LeadInterest[] = ["LOW", "MEDIUM", "HIGH"];

/** The current stage followed by the stages it may move to. */
export function availableStatuses(current: LeadStatus): LeadStatus[] {
  return [current, ...ALLOWED_STATUS_TRANSITIONS[current]];
}

/** Outcome that goes with a stage: WON is successful, LOST is unsuccessful, and leaving a closed stage clears it. */
export function outcomeForStatusChange(from: LeadStatus, to: LeadStatus): LeadOutcome | null | undefined {
  if (to === "WON") return "SUCCESSFUL";
  if (to === "LOST") return "UNSUCCESSFUL";
  if (from === "WON" || from === "LOST") return null;
  return undefined;
}

export function needsNextActionPrompt(lead: { status: LeadStatus; is_active: boolean; next_action: string | null }, to: LeadStatus): boolean {
  return lead.is_active && NEXT_ACTION_REQUIRED_STATUSES.includes(to) && !lead.next_action?.trim();
}

export function formatStageLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

export function stageTone(status: LeadStatus): "success" | "danger" | "pending" | "active" | "neutral" {
  if (status === "WON") return "success";
  if (status === "LOST") return "danger";
  if (status === "ON_HOLD") return "pending";
  if (status === "NEW") return "neutral";
  return "active";
}
