
import { api } from "../lib/api";

export type PropertyTransactionType = "SALE" | "RENT" | "LEASE";

export type PropertyType =
  | "APARTMENT"
  | "VILLA"
  | "INDEPENDENT_HOUSE"
  | "PLOT"
  | "COMMERCIAL"
  | "OTHER";

export type PropertyStatus =
  | "AVAILABLE"
  | "RESERVED"
  | "SOLD"
  | "RENTED"
  | "LEASED"
  | "UNAVAILABLE";

export interface Property {
  id: string;
  organization_id: string;
  created_at: string;
  updated_at: string;
  status: PropertyStatus | null;
  transaction_type: PropertyTransactionType | null;
  price: number | string | null;
  currency: string | null;
  rent: number | string | null;
  security_deposit: number | string | null;
  maintenance_charge: number | string | null;
  address_line_1: string | null;
  address_line_2: string | null;
  locality: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  property_type: PropertyType | null;
  bhk: number | null;
  built_up_area: number | string | null;
  carpet_area: number | string | null;
  floor_number: number | null;
  total_floors: number | null;
}

export interface PropertySearchResponse {
  items: Property[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface PropertySearchParams {
  q?: string;
  transaction_type?: PropertyTransactionType;
  status?: PropertyStatus;
  property_type?: PropertyType;
  bhk?: number;
  city?: string;
  state?: string;
  locality?: string;
  postal_code?: string;
  min_price?: number;
  max_price?: number;
  min_rent?: number;
  max_rent?: number;
  page?: number;
  page_size?: number;
}

export interface PropertyCreateInput {
  transaction_type: PropertyTransactionType;
  price: number | null;
  currency: string;
  rent: number | null;
  security_deposit: number | null;
  maintenance_charge: number | null;
  address_line_1: string;
  address_line_2?: string | null;
  locality: string;
  city: string;
  state: string;
  postal_code?: string | null;
  property_type: PropertyType;
  bhk?: number | null;
  built_up_area?: number | null;
  carpet_area?: number | null;
  floor_number?: number | null;
  total_floors?: number | null;
  status: PropertyStatus;
  source_contact_id?: string | null;
  owner_contact_id?: string | null;
}

export type PropertyCommercialInput = Pick<
  PropertyCreateInput,
  | "transaction_type"
  | "price"
  | "currency"
  | "rent"
  | "security_deposit"
  | "maintenance_charge"
>;

export type PropertyLocationInput = Pick<
  PropertyCreateInput,
  | "address_line_1"
  | "address_line_2"
  | "locality"
  | "city"
  | "state"
  | "postal_code"
  | "property_type"
  | "bhk"
  | "built_up_area"
  | "carpet_area"
  | "floor_number"
  | "total_floors"
>;

export interface PropertyAssociationInput {
  source_contact_id?: string | null;
  owner_contact_id?: string | null;
}

function buildQuery(params: PropertySearchParams = {}): string {
  const query = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }

  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export const propertiesApi = {
  search(
    params: PropertySearchParams = {},
  ): Promise<PropertySearchResponse> {
    return api.get<PropertySearchResponse>(
      `/properties/search${buildQuery(params)}`,
    );
  },

  
    create(): Promise<{
    id: string;
    organization_id: string;
    created_at: string;
    updated_at: string;
    }> {
    return api.post<{
        id: string;
        organization_id: string;
        created_at: string;
        updated_at: string;
    }>("/properties", {});
    },

  updateCommercial(
    propertyId: string,
    input: PropertyCommercialInput,
  ): Promise<Property> {
    return api.patch<Property>(
      `/properties/${encodeURIComponent(propertyId)}/commercial`,
      input,
    );
  },

  updateLocation(
    propertyId: string,
    input: PropertyLocationInput,
  ): Promise<Property> {
    return api.patch<Property>(
      `/properties/${encodeURIComponent(propertyId)}/location-attributes`,
      input,
    );
  },

  updateStatus(
    propertyId: string,
    status: PropertyStatus,
  ): Promise<Property> {
    return api.patch<Property>(
      `/properties/${encodeURIComponent(propertyId)}/status`,
      { status },
    );
  },

  updateAssociation(
    propertyId: string,
    input: PropertyAssociationInput,
  ): Promise<Property> {
    return api.patch<Property>(
      `/properties/${encodeURIComponent(propertyId)}/association`,
      input,
    );
  },
};
