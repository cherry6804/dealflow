
import { api } from "../lib/api";

export interface Contact {
  id: string;
  organization_id: string;
  first_name: string;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ContactCreateInput {
  first_name: string;
  last_name?: string | null;
  email?: string | null;
  phone?: string | null;
}

export interface ContactUpdateInput {
  first_name?: string;
  last_name?: string | null;
  email?: string | null;
  phone?: string | null;
  is_active?: boolean;
}

export interface ContactListResponse {
  items: Contact[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface ContactListParams {
  page?: number;
  page_size?: number;
  search?: string;
  is_active?: boolean;
}

function buildQuery(params: ContactListParams = {}): string {
  const query = new URLSearchParams();

  if (params.page !== undefined) {
    query.set("page", String(params.page));
  }

  if (params.page_size !== undefined) {
    query.set("page_size", String(params.page_size));
  }

  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }

  if (params.is_active !== undefined) {
    query.set("is_active", String(params.is_active));
  }

  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export const contactsApi = {
  list(params: ContactListParams = {}) {
    return api.get<ContactListResponse>(
      `/contacts${buildQuery(params)}`,
    );
  },

  get(contactId: string) {
    return api.get<Contact>(`/contacts/${encodeURIComponent(contactId)}`);
  },

  create(input: ContactCreateInput) {
    return api.post<Contact>("/contacts", input);
  },

  update(contactId: string, input: ContactUpdateInput) {
    return api.patch<Contact>(
      `/contacts/${encodeURIComponent(contactId)}`,
      input,
    );
  },
};
