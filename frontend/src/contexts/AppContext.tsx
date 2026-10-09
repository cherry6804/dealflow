import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, setCurrentOrganizationId } from "../lib/api";
import { authApi, type AuthenticatedUser } from "../services/authApi";
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

  const refreshOrganizations = useCallback(async () => {
    const availableOrganizations = await organizationApi.list();

    setOrganizations(availableOrganizations);

    setSelectedOrganizationId((currentId) => {
      const currentStillAvailable = availableOrganizations.some(
        (organization) => organization.id === currentId,
      );

      const nextId = currentStillAvailable
        ? currentId
        : (availableOrganizations[0]?.id ?? null);

      setCurrentOrganizationId(nextId);

      return nextId;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      try {
        const response = await authApi.getCurrentUser();

        if (cancelled) {
          return;
        }

        setUser(response.user);

        const availableOrganizations = await organizationApi.list();

        if (cancelled) {
          return;
        }

        setOrganizations(availableOrganizations);

        const initialOrganizationId =
          availableOrganizations[0]?.id ?? null;

        setSelectedOrganizationId(initialOrganizationId);
        setCurrentOrganizationId(initialOrganizationId);
        setStatus("authenticated");
        setError(null);
      } catch (cause) {
        if (cancelled) {
          return;
        }

        setCurrentOrganizationId(null);
        setOrganizations([]);
        setSelectedOrganizationId(null);

        if (cause instanceof ApiError && cause.status === 401) {
          setUser(null);
          setStatus("unauthenticated");
          setError(null);
          return;
        }

        setStatus("error");
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to initialize your workspace.",
        );
      }
    }

    void restoreSession();

    return () => {
      cancelled = true;
    };
  }, []);

  const selectOrganization = useCallback(
    (organizationId: string) => {
      const organizationExists = organizations.some(
        (organization) => organization.id === organizationId,
      );

      if (!organizationExists) {
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
      signOut,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}