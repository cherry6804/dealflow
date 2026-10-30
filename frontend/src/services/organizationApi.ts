import { api } from "../lib/api";

export interface Organization {
  id: string;
  name: string;
}

export const organizationApi = {
  list(): Promise<Organization[]> {
    return api.get<Organization[]>("/organizations");
  },
};