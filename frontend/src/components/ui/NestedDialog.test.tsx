import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dialog } from "./Overlays";

function dialogWithTitle(title: string): HTMLDialogElement {
  const heading = screen.getByRole("heading", { name: title });
  return heading.closest("dialog") as HTMLDialogElement;
}

/** A parent record dialog that opens a nested child dialog from one of its own buttons, the same shape as the deal record. */
function NestedHarness({ onParentClose, onChildClose }: { onParentClose: () => void; onChildClose: () => void }) {
  const [childOpen, setChildOpen] = useState(false);
  return (
    <Dialog open onClose={onParentClose} title="Deal" closeLabel="Close deal">
      <button type="button" onClick={() => setChildOpen(true)}>
        Open child
      </button>
      {childOpen ? (
        <Dialog
          open
          title="Payment milestones"
          closeLabel="Close payment milestones"
          onClose={() => {
            onChildClose();
            setChildOpen(false);
          }}
          footer={<button type="button">Child action</button>}
        >
          <input aria-label="Child field" />
        </Dialog>
      ) : null}
    </Dialog>
  );
}

describe("nested dialogs", () => {
  it("Escape with focus in the child closes only the child", () => {
    const onParentClose = vi.fn();
    const onChildClose = vi.fn();
    render(<NestedHarness onParentClose={onParentClose} onChildClose={onChildClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Open child" }));
    fireEvent.keyDown(screen.getByLabelText("Child field"), { key: "Escape" });

    expect(onChildClose).toHaveBeenCalledTimes(1);
    expect(onParentClose).not.toHaveBeenCalled();
  });

  it("a backdrop click on the child closes only the child", () => {
    const onParentClose = vi.fn();
    const onChildClose = vi.fn();
    render(<NestedHarness onParentClose={onParentClose} onChildClose={onChildClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Open child" }));
    const child = dialogWithTitle("Payment milestones");
    fireEvent.pointerDown(child);
    fireEvent.click(child);

    expect(onChildClose).toHaveBeenCalledTimes(1);
    expect(onParentClose).not.toHaveBeenCalled();
  });

  it("clicks inside the child never close the parent", () => {
    const onParentClose = vi.fn();
    render(<NestedHarness onParentClose={onParentClose} onChildClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Open child" }));
    const child = dialogWithTitle("Payment milestones");
    const action = within(child).getByRole("button", { name: "Child action" });
    fireEvent.pointerDown(action);
    fireEvent.click(action);

    expect(onParentClose).not.toHaveBeenCalled();
  });

  it("closing the child returns focus to the control that opened it, and the parent stays open", () => {
    const onParentClose = vi.fn();
    render(<NestedHarness onParentClose={onParentClose} onChildClose={vi.fn()} />);

    const opener = screen.getByRole("button", { name: "Open child" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(within(dialogWithTitle("Payment milestones")).getByRole("button", { name: "Close payment milestones" }));

    expect(document.activeElement).toBe(opener);
    expect(onParentClose).not.toHaveBeenCalled();
    expect(dialogWithTitle("Deal")).toBeTruthy();
  });

  it("the parent dialog stays usable after the child closes", () => {
    const onParentClose = vi.fn();
    render(<NestedHarness onParentClose={onParentClose} onChildClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Open child" }));
    fireEvent.click(within(dialogWithTitle("Payment milestones")).getByRole("button", { name: "Close payment milestones" }));
    fireEvent.click(screen.getByRole("button", { name: "Open child" }));

    expect(screen.getByLabelText("Child field")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close deal" }));
    expect(onParentClose).toHaveBeenCalledTimes(1);
  });

  it("locks page scrolling while any dialog is open and restores it only after the last one closes", () => {
    document.documentElement.style.overflow = "auto";
    const outer = (open: boolean) => (
      <Dialog open={open} onClose={vi.fn()} title="Outer" closeLabel="Close outer">
        <p>Outer body</p>
      </Dialog>
    );
    const inner = (open: boolean) => (
      <Dialog open={open} onClose={vi.fn()} title="Inner" closeLabel="Close inner">
        <p>Inner body</p>
      </Dialog>
    );
    const { rerender } = render(
      <>
        {outer(true)}
        {inner(false)}
      </>,
    );
    expect(document.documentElement.style.overflow).toBe("hidden");

    rerender(
      <>
        {outer(true)}
        {inner(true)}
      </>,
    );
    expect(document.documentElement.style.overflow).toBe("hidden");

    rerender(
      <>
        {outer(true)}
        {inner(false)}
      </>,
    );
    expect(document.documentElement.style.overflow).toBe("hidden");

    rerender(
      <>
        {outer(false)}
        {inner(false)}
      </>,
    );
    expect(document.documentElement.style.overflow).toBe("auto");
    document.documentElement.style.overflow = "";
  });
});
