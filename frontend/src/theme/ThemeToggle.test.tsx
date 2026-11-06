import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY } from "./theme";
import { ThemeProvider } from "./ThemeProvider";
import { ThemeToggle } from "./ThemeToggle";

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("offers light, dark and system as a labelled radio group", () => {
    renderToggle();

    const group = screen.getByRole("radiogroup", { name: "Colour theme" });
    expect(group).toBeTruthy();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByRole("radio", { name: "System theme" }).getAttribute("aria-checked")).toBe("true");
  });

  it("applies the chosen theme to the document and remembers it on this device", () => {
    renderToggle();

    fireEvent.click(screen.getByRole("radio", { name: "Dark theme" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByRole("radio", { name: "Dark theme" }).getAttribute("aria-checked")).toBe("true");
  });

  it("moves the selection with the arrow keys, as the radio group pattern requires", () => {
    renderToggle();

    act(() => {
      fireEvent.click(screen.getByRole("radio", { name: "Light theme" }));
    });
    const group = screen.getByRole("radiogroup", { name: "Colour theme" });
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Dark theme" }).getAttribute("aria-checked")).toBe("true");

    fireEvent.keyDown(group, { key: "ArrowLeft" });
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: "System theme" }).getAttribute("aria-checked")).toBe("true");
  });

  it("says so when the browser refuses to remember the choice", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      renderToggle();
      fireEvent.click(screen.getByRole("radio", { name: "Light theme" }));
      expect(screen.getByRole("status").textContent).toContain("would not remember");
      expect(document.documentElement.dataset.theme).toBe("light");
    } finally {
      spy.mockRestore();
    }
  });
});
