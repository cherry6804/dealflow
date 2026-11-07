/**
 * Theme preference logic. Pure functions only, so the rules are testable without a DOM.
 *
 * The preference is a per-device setting. It is stored in this browser's local storage and is never
 * presented as organization or team configuration.
 */

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "dealsflo.theme.preference";
export const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";

const PREFERENCES: readonly ThemePreference[] = ["light", "dark", "system"];

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (PREFERENCES as readonly string[]).includes(value);
}

/** Read the stored preference. Storage can be unavailable (private mode, blocked site data); then use the default. */
export function readStoredPreference(storage: Pick<Storage, "getItem"> | undefined): ThemePreference {
  try {
    const raw = storage?.getItem(THEME_STORAGE_KEY);
    return isThemePreference(raw) ? raw : DEFAULT_THEME_PREFERENCE;
  } catch {
    return DEFAULT_THEME_PREFERENCE;
  }
}

/** Store the preference. Returns false when storage refuses the write, so the caller can say so. */
export function writeStoredPreference(
  storage: Pick<Storage, "setItem"> | undefined,
  preference: ThemePreference,
): boolean {
  try {
    storage?.setItem(THEME_STORAGE_KEY, preference);
    return true;
  } catch {
    return false;
  }
}

/** Resolve a preference to the theme that is actually shown. "system" follows the operating system setting. */
export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}
