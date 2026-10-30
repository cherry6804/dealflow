import { api } from "../lib/api";

export type CapabilityCategory = "master" | "ai" | "automation" | "communication";

export interface CapabilityDecision {
  allowed: boolean;
  reason_code: string;
  explanation: string;
  policy_version: number;
}

export interface CapabilityState {
  capability_key: string;
  category: CapabilityCategory;
  parent_key: string | null;
  is_enabled: boolean;
  policy_version: number;
  updated_at: string | null;
  effective: CapabilityDecision;
}

export interface BudgetStatus {
  unit: string;
  period_start: string;
  period_end: string;
  limit_quantity: number;
  reserved_quantity: number;
  consumed_quantity: number;
  remaining_quantity: number;
  utilization_percent: number;
  overrun: boolean;
}

export interface BudgetList {
  period_start: string;
  period_end: string;
  items: BudgetStatus[];
}

export interface DataCategory {
  category_key: string;
  label: string;
  sensitivity: string;
  retention_treatment: string;
  producer_exists: boolean;
  note: string;
}

export interface RetentionPolicy {
  category_key: string;
  retention_days: number | null;
  version: number | null;
}

export interface LegalHold {
  id: string;
  category_key: string;
  reason: string;
  placed_at: string;
  released_at: string | null;
}

export interface PrivacyRequest {
  id: string;
  request_type: "export" | "deletion" | string;
  status: string;
  categories: string[];
  decisions: Record<string, unknown>;
  artifact_reference: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface GovernanceAccess {
  capabilities_read: boolean;
  capabilities_manage: boolean;
  usage_read: boolean;
  budgets_manage: boolean;
  privacy_read: boolean;
  privacy_manage: boolean;
}

export const governanceApi = {
  getAccess(): Promise<GovernanceAccess> {
    return api.get<GovernanceAccess>("/governance/access");
  },

  listCapabilities(): Promise<{ items: CapabilityState[] }> {
    return api.get<{ items: CapabilityState[] }>("/governance/capabilities");
  },

  setCapability(capabilityKey: string, isEnabled: boolean): Promise<CapabilityState> {
    return api.patch<CapabilityState>(`/governance/capabilities/${capabilityKey}`, {
      is_enabled: isEnabled,
      confirm: true,
    });
  },

  getBudgets(): Promise<BudgetList> {
    return api.get<BudgetList>("/governance/usage/budgets");
  },

  setBudget(unit: string, limitQuantity: number): Promise<BudgetStatus> {
    return api.put<BudgetStatus>(`/governance/usage/budgets/${unit}`, {
      limit_quantity: limitQuantity,
      confirm: true,
    });
  },

  listDataCategories(): Promise<DataCategory[]> {
    return api.get<DataCategory[]>("/governance/privacy/categories");
  },

  listRetention(): Promise<RetentionPolicy[]> {
    return api.get<RetentionPolicy[]>("/governance/privacy/retention");
  },

  setRetention(categoryKey: string, retentionDays: number | null): Promise<RetentionPolicy> {
    return api.put<RetentionPolicy>(`/governance/privacy/retention/${categoryKey}`, {
      retention_days: retentionDays,
      confirm: true,
    });
  },

  listLegalHolds(): Promise<LegalHold[]> {
    return api.get<LegalHold[]>("/governance/privacy/legal-holds");
  },

  placeLegalHold(categoryKey: string, reason: string): Promise<LegalHold> {
    return api.post<LegalHold>("/governance/privacy/legal-holds", {
      category_key: categoryKey,
      reason,
      confirm: true,
    });
  },

  releaseLegalHold(holdId: string): Promise<LegalHold> {
    return api.post<LegalHold>(`/governance/privacy/legal-holds/${holdId}/release`);
  },

  listPrivacyRequests(): Promise<PrivacyRequest[]> {
    return api.get<PrivacyRequest[]>("/governance/privacy/requests");
  },

  createPrivacyRequest(requestType: "export" | "deletion", categories: string[]): Promise<PrivacyRequest> {
    return api.post<PrivacyRequest>("/governance/privacy/requests", {
      request_type: requestType,
      categories,
      confirm: true,
    });
  },

  cancelPrivacyRequest(requestId: string): Promise<PrivacyRequest> {
    return api.post<PrivacyRequest>(`/governance/privacy/requests/${requestId}/cancel`);
  },
};
