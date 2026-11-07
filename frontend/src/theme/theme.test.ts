import { describe, expect, it } from "vitest";

import {
  DEFAULT_THEME_PREFERENCE,
  THEME_STORAGE_KEY,
  isThemePreference,
  readStoredPreference,
  resolveTheme,
  writeStoredPreference,
} from "./theme";

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

describe("theme preference", () => {
  it("accepts only the three documented preferences", () => {
    expect(isThemePreference("light")).toBe(true);
    expect(isThemePreference("dark")).toBe(true);
    expect(isThemePreference("system")).toBe(true);
    expect(isThemePreference("sepia")).toBe(false);
    expect(isThemePreference(null)).toBe(false);
  });

  it("reads a stored preference and falls back to system for anything else", () => {
    expect(readStoredPreference(memoryStorage({ [THEME_STORAGE_KEY]: "dark" }))).toBe("dark");
    expect(readStoredPreference(memoryStorage({ [THEME_STORAGE_KEY]: "neon" }))).toBe(DEFAULT_THEME_PREFERENCE);
    expect(readStoredPreference(memoryStorage())).toBe("system");
  });

  it("uses the default when storage is unavailable or throws", () => {
    const throwing = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readStoredPreference(throwing)).toBe("system");
    expect(readStoredPreference(undefined)).toBe("system");
  });

  it("reports a refused write instead of failing silently", () => {
    const refusing = {
      setItem: () => {
        throw new Error("quota");
      },
    };
    expect(writeStoredPreference(refusing, "light")).toBe(false);
    expect(writeStoredPreference(memoryStorage(), "light")).toBe(true);
  });

  it("resolves system to the operating system setting and keeps explicit choices", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});
