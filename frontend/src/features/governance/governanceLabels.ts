/**
 * Display helpers for AI governance. Units are never interpreted as currency unless the
 * unit says so, so a token count is never shown with a currency symbol.
 */

export const CAPABILITY_LABELS: Record<string, string> = {
  "ai.master": "AI features (master switch)",
  "automation.master": "Automation (master switch)",
  "ai.assistant": "AI assistant",
  "ai.agents": "AI agents",
  "ai.workflow_execution": "AI workflow execution",
  "ai.predictions": "Predictive scoring",
  "ai.content_generation": "Content generation",
  "ai.document_processing": "Document processing",
  "ai.voice": "Voice AI",
  "automation.deal_created_rules": "Deal-created automation rules",
  "channels.whatsapp": "WhatsApp messages",
  "channels.email": "Email messages",
  "channels.sms": "SMS messages",
  "channels.voice": "Voice calls",
};

export const REASON_LABELS: Record<string, string> = {
  allowed: "Running",
  unknown_capability: "Not recognised",
  master_disabled: "Turned off by a master switch",
  capability_disabled: "Turned off",
  provider_not_connected: "No verified provider connection",
  consent_not_configured: "Consent policy not configured",
};

export const UNIT_LABELS: Record<string, string> = {
  tokens_input: "Input tokens",
  tokens_output: "Output tokens",
  audio_ms: "Audio time",
  images: "Images",
  document_pages: "Document pages",
  provider_cost_minor: "Provider cost",
  customer_credits: "Customer credits",
};

export const CATEGORY_LABELS: Record<string, string> = {
  master: "Master switches",
  ai: "AI",
  automation: "Automation",
  communication: "Communication channels",
};

export function capabilityLabel(key: string): string {
  return CAPABILITY_LABELS[key] ?? key;
}

export function reasonLabel(code: string): string {
  return REASON_LABELS[code] ?? "Unavailable";
}

export function unitLabel(unit: string): string {
  return UNIT_LABELS[unit] ?? unit;
}

/** Format a unit quantity. Provider cost is minor currency units and is shown as such. */
export function formatUnitQuantity(unit: string, quantity: number, currency = "INR"): string {
  if (unit === "audio_ms") {
    const seconds = quantity / 1000;
    return `${seconds.toLocaleString(undefined, { maximumFractionDigits: 1 })} s`;
  }
  if (unit === "provider_cost_minor") {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(quantity / 100);
  }
  return quantity.toLocaleString();
}

export function sensitivityLabel(sensitivity: string): string {
  switch (sensitivity) {
    case "personal":
      return "Personal data";
    case "sensitive_content":
      return "Sensitive content";
    case "secret_reference":
      return "Secret reference";
    default:
      return "Standard";
  }
}

export function retentionLabel(treatment: string): string {
  switch (treatment) {
    case "mandatory_record":
      return "Mandatory record (not deleted on request)";
    case "never_delete_by_customer":
      return "Never deleted on request";
    default:
      return "Organization configurable";
  }
}

export function requestStatusLabel(status: string): string {
  switch (status) {
    case "awaiting_artifact_generation":
      return "Awaiting export generation";
    case "eligibility_recorded":
      return "Eligibility recorded (no deletion performed)";
    case "blocked":
      return "Blocked by policy";
    case "ready":
      return "Ready to download";
    case "expired":
      return "Expired";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}
