import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dialog } from "./Overlays";

function Harness({ dirty = false, busy = false, onClose }: { dirty?: boolean; busy?: boolean; onClose: () => void }) {
  const open = true;
  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        title="Contact — Asha Rao"
        closeLabel="Close contact"
        dirty={dirty}
        busy={busy}
        footer={<button type="button">Save changes</button>}
      >
        <input aria-label="Nickname" />
        <button type="button">Inside action</button>
      </Dialog>
    </>
  );
}

function dialogEl(): HTMLDialogElement {
  return document.querySelector("dialog.df-dialog") as HTMLDialogElement;
}

describe("shared Dialog dismissal", () => {
  it("closes when the backdrop is clicked, and the press started on the backdrop", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.pointerDown(dialogEl());
    fireEvent.click(dialogEl());
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("never closes for a click inside the dialog content", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const inside = within(dialogEl()).getByRole("button", { name: "Inside action" });
    fireEvent.pointerDown(inside);
    fireEvent.click(inside);
    fireEvent.pointerDown(within(dialogEl()).getByLabelText("Nickname"));
    fireEvent.click(dialogEl().querySelector(".df-dialog-body") as HTMLElement);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close when a press starts inside and the click lands on the backdrop", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.pointerDown(within(dialogEl()).getByLabelText("Nickname"));
    fireEvent.click(dialogEl());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on Escape and on the close control", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent(dialogEl(), new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close contact" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("asks before discarding unsaved changes, and keeps the record open when the user keeps editing", () => {
    const onClose = vi.fn();
    render(<Harness dirty onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close contact" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Discard unsaved changes?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByText("Discard unsaved changes?")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("discards after confirmation", () => {
    const onClose = vi.fn();
    render(<Harness dirty onClose={onClose} />);
    fireEvent.pointerDown(dialogEl());
    fireEvent.click(dialogEl());
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("blocks every dismissal while a request is running, so the operation is not dropped", () => {
    const onClose = vi.fn();
    render(<Harness busy onClose={onClose} />);
    fireEvent.pointerDown(dialogEl());
    fireEvent.click(dialogEl());
    fireEvent(dialogEl(), new Event("cancel", { cancelable: true }));
    expect(onClose).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Close contact" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the header title and the footer action in the dialog structure", () => {
    render(<Harness onClose={vi.fn()} />);
    expect(dialogEl().querySelector(".df-dialog-header h2")?.textContent).toBe("Contact — Asha Rao");
    expect(dialogEl().querySelector(".df-dialog-footer")?.textContent).toContain("Save changes");
  });
});
