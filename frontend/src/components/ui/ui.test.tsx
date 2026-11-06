import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Badge, Button, Checkbox, Dialog, Menu, Notification, RadioGroup, SelectField, Tabs, TextField, Tooltip } from "./index";

describe("Button", () => {
  it("is a button with its label and a loading state that blocks clicks", () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Save</Button>);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<Button loading onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
  });

  it("requires an aria-label when icon-only and hides the visible label", () => {
    render(<Button iconOnly aria-label="Delete row" icon={<span>x</span>}>Delete</Button>);
    expect(screen.getByRole("button", { name: "Delete row" })).toBeTruthy();
    expect(screen.queryByText("Delete")).toBeNull();
  });
});

describe("fields", () => {
  it("associates helper and error text and sets aria-invalid on error", () => {
    const { rerender } = render(<TextField label="Email" helper="We never share it" />);
    const input = screen.getByLabelText("Email");
    expect(input.getAttribute("aria-describedby")).toContain("-helper");

    rerender(<TextField label="Email" error="Enter a complete email" />);
    const invalid = screen.getByLabelText("Email");
    expect(invalid.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Enter a complete email");
    expect(invalid.getAttribute("aria-describedby")).toContain("-error");
  });

  it("renders select options and marks the required state", () => {
    render(
      <SelectField
        label="Stage"
        required
        options={[
          { value: "new", label: "New" },
          { value: "won", label: "Won", disabled: true },
        ]}
      />,
    );
    const select = screen.getByLabelText(/Stage/) as HTMLSelectElement;
    expect(select.required).toBe(true);
    expect(select.options).toHaveLength(2);
    expect(select.options[1].disabled).toBe(true);
  });
});

describe("Checkbox and RadioGroup", () => {
  it("sets the indeterminate state on the DOM node", () => {
    render(<Checkbox label="Select all" indeterminate onChange={() => undefined} />);
    expect((screen.getByLabelText("Select all") as HTMLInputElement).indeterminate).toBe(true);
  });

  it("moves selection with arrow keys and skips disabled options", () => {
    function Harness() {
      const [value, setValue] = useState("a");
      return (
        <RadioGroup
          name="plan"
          label="Plan"
          value={value}
          onChange={setValue}
          options={[
            { value: "a", label: "Starter" },
            { value: "b", label: "Off", disabled: true },
            { value: "c", label: "Pro" },
          ]}
        />
      );
    }
    render(<Harness />);
    const group = screen.getByRole("radiogroup", { name: "Plan" });
    fireEvent.keyDown(group, { key: "ArrowDown" });
    expect((screen.getByLabelText("Pro") as HTMLInputElement).checked).toBe(true);
    fireEvent.keyDown(group, { key: "ArrowDown" });
    expect((screen.getByLabelText("Starter") as HTMLInputElement).checked).toBe(true);
  });
});

describe("Tabs", () => {
  const tabs = [
    { id: "one", label: "One", content: <p>First panel</p> },
    { id: "two", label: "Two", content: <p>Second panel</p> },
    { id: "three", label: "Three", content: <p>Third panel</p>, disabled: true },
  ];

  it("exposes the selected tab and shows its panel", () => {
    render(<Tabs label="Sections" tabs={tabs} />);
    expect(screen.getByRole("tab", { name: "One" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").textContent).toContain("First panel");
  });

  it("moves with arrow keys, wraps and skips disabled tabs", () => {
    render(<Tabs label="Sections" tabs={tabs} />);
    const list = screen.getByRole("tablist");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Two" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "One" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Two" }).getAttribute("tabindex")).toBe("-1");
  });
});

describe("Menu", () => {
  it("opens, invokes an item and closes", () => {
    const onSelect = vi.fn();
    render(
      <Menu
        triggerLabel="Actions"
        items={[
          { id: "edit", label: "Edit", onSelect },
          { id: "delete", label: "Delete", destructive: true, onSelect: () => undefined },
        ]}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Actions" });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("menuitem", { name: "Edit" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape", () => {
    render(<Menu triggerLabel="More" items={[{ id: "a", label: "Only", onSelect: () => undefined }]} />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("Dialog", () => {
  it("names the dialog by its title and calls onClose from the close control", () => {
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} title="Delete deal?" closeLabel="Close dialog" footer={<button type="button">Cancel</button>}>
        <p>This cannot be undone.</p>
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Delete deal?" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("Tooltip", () => {
  it("shows on focus and links the text to the trigger", () => {
    render(
      <Tooltip label="Customise columns">
        <button type="button">Columns</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "Columns" });
    act(() => {
      fireEvent.focus(button);
    });
    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toBe("Customise columns");
    expect(button.getAttribute("aria-describedby")).toBe(tip.id);
  });
});

describe("Notification and Badge", () => {
  it("uses an alert role for danger and a status role otherwise", () => {
    const { rerender } = render(<Notification title="Saved" />);
    expect(screen.getByRole("status").textContent).toContain("Saved");
    rerender(<Notification tone="danger" title="Could not load" />);
    expect(screen.getByRole("alert").textContent).toContain("Could not load");
  });

  it("renders the badge label, which carries the meaning", () => {
    render(<Badge tone="success">Won</Badge>);
    expect(screen.getByText("Won").className).toContain("df-badge--success");
  });
});
