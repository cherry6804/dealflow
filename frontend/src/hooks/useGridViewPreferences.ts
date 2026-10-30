import { useCallback, useMemo, useState, useSyncExternalStore } from "react";

import { useAppContext } from "../contexts/useAppContext";
import {
  loadWorkspacePreferences,
  WORKSPACE_PREFERENCES_CHANGED_EVENT,
} from "../layouts/workspace/workspacePreferences";
import type { GridViewConfig } from "../lib/gridViewConfigs";
import {
  clearGridColumnPreferences,
  createDefaultGridColumnPreferences,
  gridColumnStorageKey,
  loadGridColumnPreferences,
  moveGridColumn,
  saveGridColumnPreferences,
  setGridColumnVisibility,
  type GridColumnPreferences,
} from "../lib/gridViewPreferences";

interface SessionPreferences {
  storageKey: string;
  preferences: GridColumnPreferences;
}

function subscribeToWorkspacePreferences(onChange: () => void) {
  window.addEventListener(WORKSPACE_PREFERENCES_CHANGED_EVENT, onChange);

  return () => {
    window.removeEventListener(WORKSPACE_PREFERENCES_CHANGED_EVENT, onChange);
  };
}

/**
 * Per-user column visibility and order for one grid, saved in this browser for
 * the signed-in user and organization. Row height follows the workspace table
 * density set in the customizer.
 */
export function useGridViewPreferences(view: GridViewConfig) {
  const { user, selectedOrganization } = useAppContext();

  const userKey = String(user?.id ?? user?.email ?? "");
  const organizationKey = String(selectedOrganization?.id ?? "");

  const storageKey =
    userKey && organizationKey
      ? gridColumnStorageKey(organizationKey, userKey, view.gridId)
      : "";

  const loaded = useMemo(
    () =>
      storageKey
        ? loadGridColumnPreferences(storageKey, view.columnOptions)
        : createDefaultGridColumnPreferences(view.columnOptions),
    [storageKey, view.columnOptions],
  );

  // Changes made this session are kept in state; the stored copy is only read
  // when the user or organization changes.
  const [session, setSession] = useState<SessionPreferences | null>(null);
  const preferences =
    session && session.storageKey === storageKey
      ? session.preferences
      : loaded;

  const density = useSyncExternalStore(
    subscribeToWorkspacePreferences,
    () => loadWorkspacePreferences(organizationKey, userKey).tableDensity,
    () => "comfortable" as const,
  );

  const columnOptions = useMemo(() => {
    const labels = new Map(
      view.columnOptions.map((option) => [option.key, option.label]),
    );
    const hidden = new Set(preferences.hidden);

    return preferences.order.map((key) => ({
      key,
      label: labels.get(key) ?? key,
      visible: !hidden.has(key),
    }));
  }, [preferences, view.columnOptions]);

  const commit = useCallback(
    (next: GridColumnPreferences) => {
      setSession({ storageKey, preferences: next });

      if (storageKey) {
        saveGridColumnPreferences(storageKey, next);
      }
    },
    [storageKey],
  );

  const setColumnVisible = useCallback(
    (key: string, visible: boolean) => {
      commit(setGridColumnVisibility(preferences, key, visible));
    },
    [commit, preferences],
  );

  const moveColumn = useCallback(
    (key: string, direction: -1 | 1) => {
      commit(moveGridColumn(preferences, key, direction));
    },
    [commit, preferences],
  );

  const resetColumns = useCallback(() => {
    const defaults = createDefaultGridColumnPreferences(view.columnOptions);

    if (storageKey) {
      clearGridColumnPreferences(storageKey);
    }

    setSession({ storageKey, preferences: defaults });
  }, [storageKey, view.columnOptions]);

  return {
    preferences,
    columnOptions,
    rowHeight: view.rowHeights[density],
    setColumnVisible,
    moveColumn,
    resetColumns,
  };
}
