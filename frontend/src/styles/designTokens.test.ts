import { describe, expect, it } from "vitest";

// Raw stylesheet sources. vite.config.ts processes CSS for tests so that ?raw imports carry the file contents.
import tokensCss from "./tokens.css?raw";
import themeCss from "./theme.css?raw";
import uiCss from "../components/ui/ui.css?raw";
import shellCss from "../components/shell/shell.css?raw";
import previewCss from "../dev/design-system/ComponentPreview.css?raw";

/**
 * Contract for the single design-token source. tokens.css holds light values on :root; theme.css holds dark values.
 * These tests enforce one token system: every token used by the new components is defined, and every colour token has a
 * dark value, so both themes cover the same roles.
 */

function declarations(source: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const match of source.matchAll(/(--df-[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    if (!map.has(match[1])) map.set(match[1], match[2].trim());
  }
  return map;
}

function darkBlock(source: string): string {
  const start = source.indexOf(':root:not([data-theme="light"])');
  return start === -1 ? "" : source.slice(start);
}

const light = declarations(tokensCss);
const darkSource = darkBlock(themeCss);
const dark = declarations(darkSource);

// Tokens that are the same in both themes on purpose (type, spacing, geometry, z-index, motion timing).
const THEME_NEUTRAL = /^--df-(font|text-|type-|space-|radius-|control-height-|grid-|sidebar-width|header-height|content-|z-|transition-|motion-|shell-)/;

describe("design token contract", () => {
  it("defines the shell dimensions in the single token source, not in a component stylesheet", () => {
    for (const name of ["--df-shell-header-height", "--df-shell-sidebar-width", "--df-shell-rail-width", "--df-shell-breadcrumb-height"]) {
      expect(light.has(name), name).toBe(true);
    }
  });

  it("defines every token referenced by the new component layer", () => {
    const referenced = new Set<string>();
    for (const source of [uiCss, shellCss, previewCss]) {
      for (const match of source.matchAll(/var\((--df-[a-z0-9-]+)/g)) {
        referenced.add(match[1]);
      }
    }
    // Set at runtime by AppShell (the sidebar column width), so it is not a static token.
    const runtimeOnly = new Set(["--df-shell-sidebar-current"]);
    const missing = [...referenced].filter((name) => !light.has(name) && !runtimeOnly.has(name));
    expect(missing).toEqual([]);
  });

  it("gives every colour token a dark value, so both themes cover the same roles", () => {
    const colourRoles = [...light.entries()]
      .filter(([name, value]) => /^(#|rgb)/.test(value) && !THEME_NEUTRAL.test(name))
      .map(([name]) => name);
    const uncovered = colourRoles.filter((name) => !dark.has(name));
    expect(uncovered).toEqual([]);
  });

  it("does not define a colour token in theme.css that tokens.css does not define", () => {
    const orphaned = [...dark.keys()].filter((name) => !light.has(name));
    expect(orphaned).toEqual([]);
  });
});
