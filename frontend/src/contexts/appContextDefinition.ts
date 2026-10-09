import { createContext } from "react";

import type { AuthenticatedUser } from "../services/authApi";
import type { Organization } from "../services/organizationApi";

export type AuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "error";

export interface AppContextValue {
  user: AuthenticatedUser | null;
  organizations: Organization[];
  selectedOrganization: Organization | null;
  status: AuthStatus;
  error: string | null;
  selectOrganization: (organizationId: string) => void;
  refreshOrganizations: () => Promise<void>;
  signOut: () => Promise<void>;
}

export const AppContext = createContext<AppContextValue | undefined>(
  undefined,
);