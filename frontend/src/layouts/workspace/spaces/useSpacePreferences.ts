import { useCallback, useState } from "react";

import { usePersonalPreference } from "../../../hooks/usePersonalPreference";
import { personalPreferenceKey } from "../../../lib/personalPreferences";
import { DEFAULT_SPACE_PREFERENCES, normalizeSpacePreferences, type SpacePreferences } from "./spacePreferences";

export const SPACE_PREFERENCES_NAMESPACE = "workspace-spaces";

interface SessionLayout {
  key: string | null;
  value: SpacePreferences;
}

/**
 * The signed-in user's sidebar layout for one organization. Without a user or organization the defaults apply and
 * nothing is written, so one user's layout never appears for another user or in another organization.
 *
 * If the browser refuses to store a change, the change still applies for this session under the same key.
 */
export function useSpacePreferences(userId: string | null, organizationId: string | null) {
  const key = personalPreferenceKey(SPACE_PREFERENCES_NAMESPACE, userId ? { userId, organizationId } : null);
  const stored = usePersonalPreference<SpacePreferences>(key, normalizeSpacePreferences, DEFAULT_SPACE_PREFERENCES);
  const [session, setSession] = useState<SessionLayout | null>(null);

  const preferences = session && session.key === key ? session.value : stored.value;

  const update = useCallback(
    (next: SpacePreferences) => {
      const saved = stored.set(next);
      setSession(saved ? null : { key, value: next });
    },
    [key, stored],
  );

  const restoreDefaults = useCallback(() => {
    stored.reset();
    setSession(null);
  }, [stored]);

  return { preferences, available: stored.available, update, restoreDefaults };
}
