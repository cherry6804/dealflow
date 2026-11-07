import { useCallback, useMemo, useState } from "react";

import { useAppContext } from "../../contexts/useAppContext";
import { usePersonalPreference } from "../../hooks/usePersonalPreference";
import { personalPreferenceKey } from "../../lib/personalPreferences";
import { normalizeFilterConditions, type GridFilterCondition, type GridFilterField } from "./gridFilters";

export const GRID_FILTER_NAMESPACE = "grid-filters";

interface SessionFilters {
  key: string | null;
  value: GridFilterCondition[];
}

/**
 * The signed-in user's filter conditions for one grid in one organization. Filters are personal: another user, or another
 * organization, never sees them. Without a user the filters apply for the session only and nothing is written. A refused
 * write still applies for the session.
 */
export function useGridFilters(gridId: string, fields: readonly GridFilterField[]) {
  const { user, selectedOrganization } = useAppContext();
  const key = personalPreferenceKey(
    GRID_FILTER_NAMESPACE,
    user ? { userId: user.id, organizationId: selectedOrganization?.id ?? null } : null,
    gridId,
  );
  const parse = useCallback((data: unknown) => normalizeFilterConditions(data, fields), [fields]);
  const fallback = useMemo<GridFilterCondition[]>(() => [], []);
  const stored = usePersonalPreference<GridFilterCondition[]>(key, parse, fallback);
  const [session, setSession] = useState<SessionFilters | null>(null);
  const conditions = session && session.key === key ? session.value : stored.value;

  const apply = useCallback(
    (next: GridFilterCondition[]) => {
      const normalized = normalizeFilterConditions(next, fields);
      if (normalized.length === 0) {
        stored.reset();
        setSession(null);
        return;
      }
      const saved = stored.set(normalized);
      setSession(saved ? null : { key, value: normalized });
    },
    [fields, key, stored],
  );

  return { conditions, apply, available: stored.available };
}
