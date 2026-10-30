
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, setCurrentOrganizationId } from "../lib/api";
import {
  authApi,
  type AuthenticatedUser,
} from "../services/authApi";
import {
  organizationApi,
  type Organization,
} from "../services/organizationApi";
import {
  AppContext,
  type AppContextValue,
  type AuthStatus,
} from "./appContextDefinition";

interface AppProviderProps {
  children: ReactNode;
}

export function AppProvider({ children }: AppProviderProps) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState<
    string | null
  >(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  const applyOrganizations = useCallback(
    (available: Organization[], preferredId?: string | null) => {
      setOrganizations(available);

      const nextId =
        available.find((organization) => organization.id === preferredId)?.id ??
        available.find(
          (organization) => organization.id === selectedOrganizationId,
        )?.id ??
        available[0]?.id ??
        null;

      setSelectedOrganizationId(nextId);
      setCurrentOrganizationId(nextId);
    },
    [selectedOrganizationId],
  );

  const refreshOrganizations = useCallback(async () => {
    const available = await organizationApi.list();
    applyOrganizations(available);
  }, [applyOrganizations]);

  const refreshSession = useCallback(
    async () => {
      setError(null);

      try {
        const response = await authApi.getCurrentUser();
        setUser(response.user);

        const available = await organizationApi.list();
        applyOrganizations(available);
        setStatus("authenticated");
      } catch (cause) {
        setCurrentOrganizationId(null);
        setUser(null);
        setOrganizations([]);
        setSelectedOrganizationId(null);

        if (cause instanceof ApiError && cause.status === 401) {
          setStatus("unauthenticated");
          setError(null);
          return;
        }

        setStatus("error");
        const message =
          cause instanceof Error
            ? cause.message
            : "Unable to initialize your workspace.";
        setError(message);
        throw cause;
      }
    },
    [applyOrganizations],
  );

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      try {
        const response = await authApi.getCurrentUser();
        if (cancelled) return;

        setUser(response.user);

        const available = await organizationApi.list();
        if (cancelled) return;

        setOrganizations(available);
        const initialId = available[0]?.id ?? null;
        setSelectedOrganizationId(initialId);
        setCurrentOrganizationId(initialId);
        setStatus("authenticated");
        setError(null);
      } catch (cause) {
        if (cancelled) return;

        setCurrentOrganizationId(null);
        setUser(null);
        setOrganizations([]);
        setSelectedOrganizationId(null);

        if (cause instanceof ApiError && cause.status === 401) {
          setStatus("unauthenticated");
          setError(null);
        } else {
          setStatus("error");
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to initialize your workspace.",
          );
        }
      }
    }

    void restoreSession();

    return () => {
      cancelled = true;
    };
  }, []);

  const selectOrganization = useCallback(
    (organizationId: string) => {
      if (!organizations.some((organization) => organization.id === organizationId)) {
        return;
      }

      setSelectedOrganizationId(organizationId);
      setCurrentOrganizationId(organizationId);
    },
    [organizations],
  );

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setCurrentOrganizationId(null);
      setUser(null);
      setOrganizations([]);
      setSelectedOrganizationId(null);
      setStatus("unauthenticated");
      setError(null);
    }
  }, []);

  const selectedOrganization =
    organizations.find(
      (organization) => organization.id === selectedOrganizationId,
    ) ?? null;

  const value = useMemo<AppContextValue>(
    () => ({
      user,
      organizations,
      selectedOrganization,
      status,
      error,
      selectOrganization,
      refreshOrganizations,
      refreshSession,
      signOut,
    }),
    [
      user,
      organizations,
      selectedOrganization,
      status,
      error,
      selectOrganization,
      refreshOrganizations,
      refreshSession,
      signOut,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
