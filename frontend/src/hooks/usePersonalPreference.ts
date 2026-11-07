import { useCallback, useSyncExternalStore } from "react";

import {
  parsePersonalPreference,
  readRawPreference,
  removePersonalPreference,
  subscribePersonalPreferences,
  writePersonalPreference,
  type ParseOptions,
} from "../lib/personalPreferences";

export interface PersonalPreferenceResult<T> {
  value: T;
  /** Saves a new value under this key only. Returns false when the browser refused to store it. */
  set: (next: T) => boolean;
  /** Removes this key only, so the fallback applies again. */
  reset: () => void;
  /** False when no key is available (no signed-in user); the fallback is returned and nothing is written. */
  available: boolean;
}

/**
 * Reads one personal preference for the current key. The key is derived from the signed-in user and organization, so a
 * change of user or organization changes the key and the value follows it. Changes made elsewhere in this tab or in
 * another tab are picked up without a reload.
 */
export function usePersonalPreference<T>(
  key: string | null,
  parse: (data: unknown) => T | null,
  fallback: T,
  options?: ParseOptions,
): PersonalPreferenceResult<T> {
  const subscribe = useCallback((onChange: () => void) => subscribePersonalPreferences(onChange), []);
  const getSnapshot = useCallback(() => readRawPreference(key), [key]);
  const raw = useSyncExternalStore(subscribe, getSnapshot, () => null);

  // Parsing is a small JSON read, so it runs on each render rather than being memoized against inline parser callbacks.
  // Callers should keep their fallback values in module-level constants so their own effects stay stable.
  const value = parsePersonalPreference(raw, parse, fallback, options);

  const set = useCallback((next: T) => writePersonalPreference(key, next), [key]);
  const reset = useCallback(() => removePersonalPreference(key), [key]);

  return { value, set, reset, available: key !== null };
}
