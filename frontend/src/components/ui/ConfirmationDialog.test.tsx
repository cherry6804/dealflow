import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmationDialog } from "./ConfirmationDialog";

function setup(overrides: Partial<Parameters<typeof ConfirmationDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmationDialog
      open
      title="Deactivate customer?"
      message="The profile will leave active customers."
      confirmLabel="Deactivate"
      tone="danger"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe("ConfirmationDialog", () => {
  it("states the consequence and confirms only on the confirm button", () => {
    const { onConfirm, onCancel } = setup();
    expect(screen.getByText("The profile will leave active customers.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels from the cancel button and from Escape, without confirming", () => {
    const { onConfirm, onCancel } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent(document.querySelector("dialog.df-dialog") as HTMLDialogElement, new Event("cancel", { cancelable: true }));
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("blocks cancelling while the confirmed action is running", () => {
    const { onCancel } = setup({ busy: true });
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onCancel).not.toHaveBeenCalled();
  });
});
