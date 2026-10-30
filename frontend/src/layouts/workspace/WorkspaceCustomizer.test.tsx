import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import WorkspaceCustomizer from "./WorkspaceCustomizer";
import {
  DEFAULT_WORKSPACE_PREFERENCES,
  type WorkspacePreferences,
} from "./workspacePreferences";
import { WORKSPACE_MODULE_LABELS, WORKSPACE_SPACE_IDS } from "./workspaceSpaces";

function renderCustomizer(overrides: Partial<WorkspacePreferences> = {}) {
  const onChange = vi.fn();
  const preferences = { ...DEFAULT_WORKSPACE_PREFERENCES, ...overrides };

  render(
    <WorkspaceCustomizer
      open
      preferences={preferences}
      availableModules={[...WORKSPACE_MODULE_LABELS]}
      onClose={vi.fn()}
      onChange={onChange}
      onReset={vi.fn()}
    />,
  );

  return { onChange };
}

describe("WorkspaceCustomizer space order", () => {
  it("moves a space down and reports the new personal order", async () => {
    const user = userEvent.setup();
    const { onChange } = renderCustomizer();

    await user.click(screen.getByRole("button", { name: "Move Sales space down" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        spaceOrder: ["deals-revenue", "sales", "property", "partners", "operations"],
      }),
    );
  });

  it("disables moving the first space up and the last space down", () => {
    renderCustomizer();

    expect(
      (screen.getByRole("button", { name: "Move Sales space up" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Move Operations space down" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("resets space order to the approved default", async () => {
    const user = userEvent.setup();
    const { onChange } = renderCustomizer({
      spaceOrder: ["partners", "sales", "deals-revenue", "property", "operations"],
    });

    await user.click(screen.getByRole("button", { name: "Reset space order" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ spaceOrder: [...WORKSPACE_SPACE_IDS] }),
    );
  });

  it("disables the space reset when the order is already the default", () => {
    renderCustomizer();

    expect(
      (screen.getByRole("button", { name: "Reset space order" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
