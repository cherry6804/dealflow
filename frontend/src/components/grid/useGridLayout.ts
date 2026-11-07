import { useCallback, useMemo, useState } from "react";

import { useAppContext } from "../../contexts/useAppContext";
import { usePersonalPreference } from "../../hooks/usePersonalPreference";
import { personalPreferenceKey } from "../../lib/personalPreferences";
import { createDefaultGridLayout, normalizeGridLayout, type GridColumnDef, type GridLayout } from "./gridLayout";

export const GRID_LAYOUT_NAMESPACE = "grid-layout";

interface SessionLayout {
  key: string | null;
  value: GridLayout;
}

/**
 * The signed-in user's layout for one grid in one organization: column order, visibility, widths, pinning and density.
 * Without a user the defaults apply and nothing is written. A refused write still applies for the session.
 */
export function useGridLayout(gridId: string, columns: readonly GridColumnDef[]) {
  const { user, selectedOrganization } = useAppContext();
  const key = personalPreferenceKey(
    GRID_LAYOUT_NAMESPACE,
    user ? { userId: user.id, organizationId: selectedOrganization?.id ?? null } : null,
    gridId,
  );
  const fallback = useMemo(() => createDefaultGridLayout(columns), [columns]);
  const parse = useCallback((data: unknown) => normalizeGridLayout(data, columns), [columns]);
  const stored = usePersonalPreference<GridLayout>(key, parse, fallback);
  const [session, setSession] = useState<SessionLayout | null>(null);
  const layout = session && session.key === key ? session.value : stored.value;

  const update = useCallback(
    (next: GridLayout) => {
      const saved = stored.set(next);
      setSession(saved ? null : { key, value: next });
    },
    [key, stored],
  );

  const resetLayout = useCallback(() => {
    stored.reset();
    setSession(null);
  }, [stored]);

  return { layout, available: stored.available, update, resetLayout };
}
