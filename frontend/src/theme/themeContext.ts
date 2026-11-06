import { createContext } from "react";

import type { ResolvedTheme, ThemePreference } from "./theme";

export type ThemeContextValue = {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
  /** False when the browser refused to remember the choice. The choice still applies for this page view. */
  persisted: boolean;
};

export const ThemeContext = createContext<ThemeContextValue | null>(null);
