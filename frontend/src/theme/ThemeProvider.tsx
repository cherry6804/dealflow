import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ThemeContext, type ThemeContextValue } from "./themeContext";
import {
  readStoredPreference,
  resolveTheme,
  writeStoredPreference,
  type ThemePreference,
} from "./theme";

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
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    readStoredPreference(getLocalStorage()),
  );
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

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    setPersisted(writeStoredPreference(getLocalStorage(), next));
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, resolved, setPreference, persisted }),
    [preference, resolved, setPreference, persisted],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
