import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RemoveMemberDialog, { REMOVAL_REASON_MAX_LENGTH } from "./RemoveMemberDialog";

function renderDialog(overrides: Partial<Parameters<typeof RemoveMemberDialog>[0]> = {}) {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  render(
    <RemoveMemberDialog
      open
      memberName="Asha Rao"
      submitting={false}
      error={null}
      onClose={onClose}
      onSubmit={onSubmit}
      {...overrides}
    />,
  );
  return { onSubmit, onClose };
}

describe("RemoveMemberDialog", () => {
  it("names the member and explains what is released", () => {
    renderDialog();

    expect(screen.getByRole("dialog", { name: "Remove Asha Rao?" })).toBeTruthy();
    expect(screen.getByText(/releases their Dealsflo seat in SIBVO/)).toBeTruthy();
  });

  it("requires a reason and does not submit an empty one", async () => {
    const { onSubmit } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));

    expect(await screen.findByText("Enter a reason for removing this member.")).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a whitespace-only reason", async () => {
    const { onSubmit } = renderDialog();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));

    expect(await screen.findByText("Enter a reason for removing this member.")).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a reason longer than the server accepts", async () => {
    const { onSubmit } = renderDialog();
    const tooLong = "x".repeat(REMOVAL_REASON_MAX_LENGTH + 1);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: tooLong } });
    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));

    expect(
      await screen.findByText(`The reason must be ${REMOVAL_REASON_MAX_LENGTH} characters or fewer.`),
    ).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the trimmed reason", async () => {
    const { onSubmit } = renderDialog();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  Left the brokerage  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("Left the brokerage"));
  });

  it("shows the SIBVO failure from the last attempt and keeps the dialog open", () => {
    renderDialog({
      error: "SIBVO did not confirm the removal, so Asha Rao is still a member. Try again.",
    });

    expect(screen.getByRole("alert").textContent).toContain("still a member");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("disables actions and says it is waiting while SIBVO confirms", () => {
    renderDialog({ submitting: true });

    expect(screen.getByRole("button", { name: "Waiting for SIBVO…" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Cancel" }).hasAttribute("disabled")).toBe(true);
  });

  it("closes when cancelled", () => {
    const { onClose } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalled();
  });
});
