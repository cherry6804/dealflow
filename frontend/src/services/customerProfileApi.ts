import { api } from "../lib/api";

export interface CustomerProfileContact {
  id: string;
  first_name: string;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
}

export interface CustomerProfile {
  id: string;
  organization_id: string;
  contact_id: string;
  is_active: boolean;
  customer_notes: string | null;
  created_at: string;
  updated_at: string;
  contact: CustomerProfileContact;
}

export interface CustomerProfileListResponse {
  items: CustomerProfile[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface CustomerProfileListParams {
  page?: number;
  page_size?: number;
  search?: string;
  is_active?: boolean;
}

export interface RegisterCustomerProfileInput {
  contact_id: string;
  customer_notes?: string | null;
}

export interface UpdateCustomerProfileInput {
  customer_notes?: string | null;
  is_active?: boolean;
}

export const customerProfilesApi = {
  list(
    params: CustomerProfileListParams = {},
  ): Promise<CustomerProfileListResponse> {
    const query = new URLSearchParams();

    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.page_size ?? 10));

    if (params.search?.trim()) {
      query.set("search", params.search.trim());
    }

    if (params.is_active !== undefined) {
      query.set("is_active", String(params.is_active));
    }

    return api.get<CustomerProfileListResponse>(
      `/customer-profiles?${query.toString()}`,
    );
  },

  get(customerProfileId: string): Promise<CustomerProfile> {
    return api.get<CustomerProfile>(
      `/customer-profiles/${encodeURIComponent(customerProfileId)}`,
    );
  },

  register(
    input: RegisterCustomerProfileInput,
  ): Promise<CustomerProfile> {
    return api.post<CustomerProfile>("/customer-profiles", input);
  },

  update(
    customerProfileId: string,
    input: UpdateCustomerProfileInput,
  ): Promise<CustomerProfile> {
    return api.patch<CustomerProfile>(
      `/customer-profiles/${encodeURIComponent(customerProfileId)}`,
      input,
    );
  },

  deactivate(customerProfileId: string): Promise<CustomerProfile> {
    return api.delete<CustomerProfile>(
      `/customer-profiles/${encodeURIComponent(customerProfileId)}`,
    );
  },
};
