
import { api } from "../lib/api";

export type RequirementStatus = "ACTIVE" | "INACTIVE";

export type PropertyType =
  | "APARTMENT"
  | "VILLA"
  | "INDEPENDENT_HOUSE"
  | "PLOT"
  | "COMMERCIAL"
  | "OTHER";

export type PossessionPreference =
  | "READY_TO_MOVE"
  | "WITHIN_3_MONTHS"
  | "WITHIN_6_MONTHS"
  | "WITHIN_12_MONTHS"
  | "AFTER_12_MONTHS"
  | "ANY";

export type ParkingPreference =
  | "REQUIRED"
  | "PREFERRED"
  | "NOT_REQUIRED"
  | "ANY";

export interface CustomerRequirement {
  id: string;
  organization_id: string;
  status: RequirementStatus;
  is_active: boolean;
  budget_min: string | number | null;
  budget_max: string | number | null;
  budget_currency: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerRequirementListResponse {
  items: CustomerRequirement[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface RequirementListParams {
  page?: number;
  page_size?: number;
  status?: RequirementStatus;
}

export interface RequirementUpdateInput {
  status?: RequirementStatus | null;
  is_active?: boolean | null;
  budget_min?: string | number | null;
  budget_max?: string | number | null;
  budget_currency?: string | null;
}

export interface RequirementLocation {
  id: string;
  organization_id: string;
  customer_requirement_id: string;
  city: string;
  locality: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RequirementLocationCreateInput {
  city: string;
  locality: string;
}

export interface RequirementLocationUpdateInput {
  city?: string | null;
  locality?: string | null;
  is_active?: boolean | null;
}

export interface RequirementPropertyPreference {
  id: string;
  organization_id: string;
  customer_requirement_id: string;
  property_type: PropertyType;
  bhk_min: number | null;
  bhk_max: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RequirementPropertyPreferenceCreateInput {
  property_type: PropertyType;
  bhk_min?: number | null;
  bhk_max?: number | null;
}

export interface RequirementPropertyPreferenceUpdateInput {
  property_type?: PropertyType | null;
  bhk_min?: number | null;
  bhk_max?: number | null;
  is_active?: boolean | null;
}

export interface RequirementPossessionParkingPreference {
  id: string;
  organization_id: string;
  customer_requirement_id: string;
  possession_preference: PossessionPreference;
  parking_preference: ParkingPreference;
  parking_spaces_min: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RequirementPossessionParkingCreateInput {
  possession_preference: PossessionPreference;
  parking_preference: ParkingPreference;
  parking_spaces_min?: number | null;
}

export interface RequirementPossessionParkingUpdateInput {
  possession_preference?: PossessionPreference | null;
  parking_preference?: ParkingPreference | null;
  parking_spaces_min?: number | null;
  is_active?: boolean | null;
}

export interface RequirementAssociation {
  customer_requirement_id: string;
  organization_id: string;
  lead_id: string | null;
  customer_profile_id: string | null;
  updated_at: string;
}

export interface RequirementAssociationInput {
  lead_id?: string | null;
  customer_profile_id?: string | null;
}

export interface RequirementHistoryEntry {
  id: string;
  customer_requirement_id: string;
  organization_id: string;
  version: number;
  actor_id: string;
  occurred_at: string;
  change_type: string;
  snapshot: Record<string, unknown>;
}

export interface RequirementHistoryListResponse {
  items: RequirementHistoryEntry[];
}

function requirementPath(requirementId: string): string {
  return `/customer-requirements/${encodeURIComponent(requirementId)}`;
}



export const requirementsApi = {
  list(params?: {
  page?: number;
  page_size?: number;
  status?: RequirementStatus;
}): Promise<CustomerRequirementListResponse> {
  const query = new URLSearchParams();

  if (params?.page !== undefined) {
    query.set("page", String(params.page));
  }

  if (params?.page_size !== undefined) {
    query.set("page_size", String(params.page_size));
  }

  if (params?.status) {
    query.set("status", params.status);
  }

  const suffix = query.size > 0 ? `?${query.toString()}` : "";

  return api.get<CustomerRequirementListResponse>(
    `/customer-requirements${suffix}`,
  );
},

  create(): Promise<CustomerRequirement> {
    return api.post<CustomerRequirement>("/customer-requirements", {});
  },

  get(requirementId: string): Promise<CustomerRequirement> {
    return api.get<CustomerRequirement>(requirementPath(requirementId));
  },

  update(
    requirementId: string,
    input: RequirementUpdateInput,
  ): Promise<CustomerRequirement> {
    return api.patch<CustomerRequirement>(
      requirementPath(requirementId),
      input,
    );
  },

  listLocations(requirementId: string): Promise<RequirementLocation[]> {
    return api.get<RequirementLocation[]>(
      `${requirementPath(requirementId)}/locations`,
    );
  },

  createLocation(
    requirementId: string,
    input: RequirementLocationCreateInput,
  ): Promise<RequirementLocation> {
    return api.post<RequirementLocation>(
      `${requirementPath(requirementId)}/locations`,
      input,
    );
  },

  updateLocation(
    requirementId: string,
    locationId: string,
    input: RequirementLocationUpdateInput,
  ): Promise<RequirementLocation> {
    return api.patch<RequirementLocation>(
      `${requirementPath(requirementId)}/locations/${encodeURIComponent(locationId)}`,
      input,
    );
  },

  listPropertyPreferences(
    requirementId: string,
  ): Promise<RequirementPropertyPreference[]> {
    return api.get<RequirementPropertyPreference[]>(
      `${requirementPath(requirementId)}/property-preferences`,
    );
  },

  createPropertyPreference(
    requirementId: string,
    input: RequirementPropertyPreferenceCreateInput,
  ): Promise<RequirementPropertyPreference> {
    return api.post<RequirementPropertyPreference>(
      `${requirementPath(requirementId)}/property-preferences`,
      input,
    );
  },

  updatePropertyPreference(
    requirementId: string,
    preferenceId: string,
    input: RequirementPropertyPreferenceUpdateInput,
  ): Promise<RequirementPropertyPreference> {
    return api.patch<RequirementPropertyPreference>(
      `${requirementPath(requirementId)}/property-preferences/${encodeURIComponent(preferenceId)}`,
      input,
    );
  },

  getPossessionParking(
    requirementId: string,
  ): Promise<RequirementPossessionParkingPreference> {
    return api.get<RequirementPossessionParkingPreference>(
      `${requirementPath(requirementId)}/possession-parking-preference`,
    );
  },

  createPossessionParking(
    requirementId: string,
    input: RequirementPossessionParkingCreateInput,
  ): Promise<RequirementPossessionParkingPreference> {
    return api.post<RequirementPossessionParkingPreference>(
      `${requirementPath(requirementId)}/possession-parking-preference`,
      input,
    );
  },

  updatePossessionParking(
    requirementId: string,
    input: RequirementPossessionParkingUpdateInput,
  ): Promise<RequirementPossessionParkingPreference> {
    return api.patch<RequirementPossessionParkingPreference>(
      `${requirementPath(requirementId)}/possession-parking-preference`,
      input,
    );
  },

  getAssociation(requirementId: string): Promise<RequirementAssociation> {
    return api.get<RequirementAssociation>(
      `${requirementPath(requirementId)}/association`,
    );
  },

  createAssociation(
    requirementId: string,
    input: RequirementAssociationInput,
  ): Promise<RequirementAssociation> {
    return api.post<RequirementAssociation>(
      `${requirementPath(requirementId)}/association`,
      input,
    );
  },

  updateAssociation(
    requirementId: string,
    input: RequirementAssociationInput,
  ): Promise<RequirementAssociation> {
    return api.patch<RequirementAssociation>(
      `${requirementPath(requirementId)}/association`,
      input,
    );
  },

  listHistory(
    requirementId: string,
  ): Promise<RequirementHistoryListResponse> {
    return api.get<RequirementHistoryListResponse>(
      `${requirementPath(requirementId)}/history`,
    );
  },

  getHistoryVersion(
    requirementId: string,
    version: number,
  ): Promise<RequirementHistoryEntry> {
    return api.get<RequirementHistoryEntry>(
      `${requirementPath(requirementId)}/history/${version}`,
    );
  },
};
