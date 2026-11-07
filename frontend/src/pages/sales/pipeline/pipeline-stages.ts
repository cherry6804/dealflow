import type { LeadStatus } from "../../../services/leadApi";

export interface PipelineStageDefinition {
  readonly status: LeadStatus;
  readonly label: string;
  readonly description: string;
}

/**
 * Pipeline columns, in order. These are the stages the Leads and Pipeline pages already use. Transitions come from
 * ALLOWED_STATUS_TRANSITIONS in lead-workflow, the same table the record dialog enforces.
 */
export const PIPELINE_STAGES: readonly PipelineStageDefinition[] = [
  { status: "NEW", label: "New", description: "Recently captured" },
  { status: "CONTACTED", label: "Contacted", description: "First contact made" },
  { status: "QUALIFIED", label: "Qualified", description: "Potential confirmed" },
  { status: "MATCHING", label: "Matching", description: "Finding suitable options" },
  { status: "VISIT", label: "Visit", description: "Property visits" },
  { status: "NEGOTIATION", label: "Negotiation", description: "Discussing terms" },
  { status: "WON", label: "Won", description: "Successful opportunities" },
  { status: "LOST", label: "Lost", description: "Unsuccessful opportunities" },
  { status: "ON_HOLD", label: "On hold", description: "Temporarily paused" },
];
