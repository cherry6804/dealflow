import { useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { AppContext } from "../contexts/appContextDefinition";
import { usePersonalPreference } from "../hooks/usePersonalPreference";
import { personalPreferenceKey } from "../lib/personalPreferences";
import { ThemeContext, type ThemeContextValue } from "./themeContext";
import {
  DEFAULT_THEME_PREFERENCE,
  isThemePreference,
  readStoredPreference,
  resolveTheme,
  writeStoredPreference,
  type ThemePreference,
} from "./theme";

/** Theme is personal: stored under the signed-in user's key, so it follows that user, not the device or other users. */
const THEME_NAMESPACE = "theme";

function parseThemePreference(data: unknown): ThemePreference | null {
  return isThemePreference(data) ? data : null;
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

function getLocalStorage(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Optional: the theme also applies on pages that render outside a signed-in session (sign-in, sign-up).
  const userId = useContext(AppContext)?.user?.id ?? null;
  const userKey = personalPreferenceKey(THEME_NAMESPACE, userId ? { userId, organizationId: null } : null);
  const personal = usePersonalPreference<ThemePreference | null>(userKey, parseThemePreference, null);

  // Device-level choice, used when no one is signed in.
  const [devicePreference, setDevicePreference] = useState<ThemePreference>(() =>
    readStoredPreference(getLocalStorage()),
  );
  // When the browser refuses to store a personal choice, it still applies for this session, under the same key.
  const [sessionChoice, setSessionChoice] = useState<{ key: string; value: ThemePreference } | null>(null);
  const sessionOverride = userKey && sessionChoice && sessionChoice.key === userKey ? sessionChoice.value : null;
  const preference: ThemePreference = userKey
    ? (sessionOverride ?? personal.value ?? DEFAULT_THEME_PREFERENCE)
    : devicePreference;
  const [prefersDark, setPrefersDark] = useState<boolean>(systemPrefersDark);
  const [persisted, setPersisted] = useState(true);

  const resolved = resolveTheme(preference, prefersDark);

  // Follow the operating system while the preference is "system".
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => setPrefersDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  // Apply the resolved theme to the document root. Tokens in styles/tokens.css read this attribute.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolved;
    root.style.colorScheme = resolved;
    return () => {
      delete root.dataset.theme;
      root.style.colorScheme = "";
    };
  }, [resolved]);

  const setPreference = useCallback(
    (next: ThemePreference) => {
      if (userKey) {
        const saved = personal.set(next);
        setPersisted(saved);
        setSessionChoice(saved ? null : { key: userKey, value: next });
        return;
      }
      setDevicePreference(next);
      setPersisted(writeStoredPreference(getLocalStorage(), next));
    },
    [userKey, personal],
  );

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, resolved, setPreference, persisted }),
    [preference, resolved, setPreference, persisted],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
