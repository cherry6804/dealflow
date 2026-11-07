import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DealCommission, PaymentMilestone } from "../services/dealApi";
import { dealCommissionsApi, paymentMilestonesApi } from "../services/dealApi";
import DealCommissionsPanel from "./DealCommissionsPanel";
import PaymentMilestonesPanel from "./PaymentMilestonesPanel";

vi.mock("../services/dealApi", () => ({
  paymentMilestonesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), markPaid: vi.fn(), cancel: vi.fn() },
  dealCommissionsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), agree: vi.fn(), markPaid: vi.fn(), cancel: vi.fn() },
}));

const milestoneApi = vi.mocked(paymentMilestonesApi);
const commissionApi = vi.mocked(dealCommissionsApi);

function milestone(overrides: Partial<PaymentMilestone> = {}): PaymentMilestone {
  return {
    id: "m1",
    organization_id: "o1",
    deal_id: "d1",
    name: "Booking advance",
    amount: "500000",
    currency: "INR",
    due_at: "2026-12-01T10:00:00Z",
    notes: null,
    status: "PENDING",
    paid_at: null,
    payment_reference: null,
    paid_by_user_id: null,
    created_by_user_id: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    is_overdue: false,
    ...overrides,
  };
}

function commission(overrides: Partial<DealCommission> = {}): DealCommission {
  return {
    id: "c1",
    organization_id: "o1",
    deal_id: "d1",
    commission_type: "PERCENTAGE",
    fixed_amount: null,
    rate_percent: "2",
    currency: "INR",
    status: "PROPOSED",
    terms: null,
    agreed_at: null,
    paid_at: null,
    payment_reference: null,
    created_by_user_id: null,
    updated_by_user_id: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    calculated_amount: "10000.00",
    ...overrides,
  };
}

/** Finds a visible dialog by its heading. The parent and nested dialogs are all in the document. */
function dialogTitled(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("dialog") as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PaymentMilestonesPanel workflow", () => {
  it("lists milestones with amount, due date and status", async () => {
    milestoneApi.list.mockResolvedValue({ items: [milestone(), milestone({ id: "m2", name: "Final", is_overdue: true })], total: 2 });
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Asha · Sea View" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);

    expect(await screen.findByRole("list", { name: "Payment milestones" })).toBeTruthy();
    expect(screen.getByText("Booking advance")).toBeTruthy();
    expect(screen.getAllByText("Overdue").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/5,00,000/).length).toBeGreaterThan(0);
  });

  it("shows an empty state with a way to add the first milestone", async () => {
    milestoneApi.list.mockResolvedValue({ items: [], total: 0 });
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByText("No payment milestones yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add first milestone" })).toBeTruthy();
  });

  it("shows an error with a retry when the list cannot load", async () => {
    milestoneApi.list.mockRejectedValueOnce(new Error("Network down")).mockResolvedValueOnce({ items: [], total: 0 });
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);

    expect((await screen.findByRole("alert")).textContent).toContain("Network down");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No payment milestones yet")).toBeTruthy();
  });

  it("does not submit an invalid milestone and explains each problem", async () => {
    milestoneApi.list.mockResolvedValue({ items: [], total: 0 });
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Add first milestone" }));

    const form = document.getElementById("payment-milestone-form") as HTMLFormElement;
    fireEvent.submit(form);

    expect(await screen.findByText("Enter a milestone name.")).toBeTruthy();
    expect(screen.getByText("Enter an amount.")).toBeTruthy();
    expect(milestoneApi.create).not.toHaveBeenCalled();
  });

  it("creates a milestone, reports the change to the parent deal and reloads the list", async () => {
    milestoneApi.list.mockResolvedValueOnce({ items: [], total: 0 }).mockResolvedValueOnce({ items: [milestone({ name: "Final payment" })], total: 1 });
    milestoneApi.create.mockResolvedValue(milestone({ name: "Final payment" }));
    const onChanged = vi.fn();
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={vi.fn()} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Add first milestone" }));
    fireEvent.change(screen.getByLabelText(/Milestone name/), { target: { value: "Final payment" } });
    fireEvent.change(screen.getByLabelText(/^Amount/), { target: { value: "250000.50" } });
    fireEvent.change(screen.getByLabelText(/Due date and time/), { target: { value: "2026-12-15T09:30" } });
    fireEvent.submit(document.getElementById("payment-milestone-form") as HTMLFormElement);

    await waitFor(() => expect(milestoneApi.create).toHaveBeenCalledTimes(1));
    const [dealId, input] = milestoneApi.create.mock.calls[0];
    expect(dealId).toBe("d1");
    expect(input.name).toBe("Final payment");
    expect(input.amount).toBe(250000.5);
    expect(input.currency).toBe("INR");
    expect(onChanged).toHaveBeenCalledWith("Payment milestone created.");
    expect(await screen.findByText("Final payment")).toBeTruthy();
  });

  it("records a payment with its reference only after the payment step is confirmed", async () => {
    milestoneApi.list.mockResolvedValue({ items: [milestone()], total: 1 });
    milestoneApi.markPaid.mockResolvedValue(milestone({ status: "PAID", paid_at: "2026-11-07T00:00:00Z" }));
    const onChanged = vi.fn();
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={vi.fn()} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Record payment" }));
    const payment = dialogTitled("Record payment");
    fireEvent.change(within(payment).getByLabelText(/Payment reference/), { target: { value: "UTR-123" } });
    fireEvent.click(within(payment).getByRole("button", { name: "Record payment" }));

    await waitFor(() => expect(milestoneApi.markPaid).toHaveBeenCalledWith("m1", { payment_reference: "UTR-123" }));
    expect(onChanged).toHaveBeenCalledWith('"Booking advance" marked as paid.');
  });

  it("asks before cancelling a milestone and does nothing when the user keeps it", async () => {
    milestoneApi.list.mockResolvedValue({ items: [milestone()], total: 1 });
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Cancel milestone" }));
    const confirm = screen.getByRole("heading", { name: "Cancel payment milestone?" }).closest("dialog") as HTMLElement;
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));

    expect(milestoneApi.cancel).not.toHaveBeenCalled();
  });

  it("closing the nested form keeps the milestones dialog open and usable", async () => {
    milestoneApi.list.mockResolvedValue({ items: [milestone()], total: 1 });
    const onClose = vi.fn();
    render(<PaymentMilestonesPanel dealId="d1" dealTitle="Deal" currency="INR" onClose={onClose} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit milestone" }));
    expect(screen.getByRole("heading", { name: "Edit payment milestone" })).toBeTruthy();
    fireEvent.click(within(dialogTitled("Edit payment milestone")).getByRole("button", { name: "Back" }));

    expect(screen.queryByRole("heading", { name: "Edit payment milestone" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Record payment" })).toBeTruthy();
  });
});

describe("DealCommissionsPanel workflow", () => {
  it("never totals a commission without a calculated amount as zero, and keeps currencies apart", async () => {
    commissionApi.list.mockResolvedValue({
      items: [
        commission({ id: "a", status: "AGREED", calculated_amount: "10000.00" }),
        commission({ id: "b", status: "AGREED", calculated_amount: null }),
        commission({ id: "c", status: "PAID", currency: "USD", calculated_amount: "300.00" }),
      ],
      total: 3,
    });
    render(<DealCommissionsPanel dealId="d1" dealTitle="Deal" dealValue={null} currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);

    const totals = await screen.findByRole("list", { name: "Commissions" });
    expect(totals).toBeTruthy();
    expect(screen.getByText(/1 without a calculated amount/)).toBeTruthy();
    expect(screen.getAllByText(/300\.00/).length).toBeGreaterThan(0);
  });

  it("rejects a percentage above 100 before calling the API", async () => {
    commissionApi.list.mockResolvedValue({ items: [], total: 0 });
    render(<DealCommissionsPanel dealId="d1" dealTitle="Deal" dealValue="5000000" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Add first commission" }));
    fireEvent.change(screen.getByLabelText(/Commission rate/), { target: { value: "120" } });
    fireEvent.submit(document.getElementById("deal-commission-form") as HTMLFormElement);

    expect(await screen.findByText("Commission percentage cannot exceed 100%.")).toBeTruthy();
    expect(commissionApi.create).not.toHaveBeenCalled();
  });

  it("agrees to proposed terms after confirmation and reports the change", async () => {
    commissionApi.list.mockResolvedValue({ items: [commission()], total: 1 });
    commissionApi.agree.mockResolvedValue(commission({ status: "AGREED" }));
    const onChanged = vi.fn();
    render(<DealCommissionsPanel dealId="d1" dealTitle="Deal" dealValue="500000" currency="INR" onClose={vi.fn()} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Agree terms" }));
    const confirm = screen.getByRole("heading", { name: "Agree to commission terms?" }).closest("dialog") as HTMLElement;
    fireEvent.click(within(confirm).getByRole("button", { name: "Agree terms" }));

    await waitFor(() => expect(commissionApi.agree).toHaveBeenCalledWith("c1"));
    expect(onChanged).toHaveBeenCalledWith("Commission terms agreed.");
  });

  it("records payment for an agreed commission with an optional reference", async () => {
    commissionApi.list.mockResolvedValue({ items: [commission({ status: "AGREED" })], total: 1 });
    commissionApi.markPaid.mockResolvedValue(commission({ status: "PAID" }));
    render(<DealCommissionsPanel dealId="d1" dealTitle="Deal" dealValue="500000" currency="INR" onClose={vi.fn()} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Record payment" }));
    const payment = dialogTitled("Record commission payment");
    fireEvent.click(within(payment).getByRole("button", { name: "Record payment" }));

    await waitFor(() => expect(commissionApi.markPaid).toHaveBeenCalledWith("c1", { payment_reference: null }));
  });
});
