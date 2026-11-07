import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { contactsApi } from "../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../services/customerProfileApi";
import CustomersWorkspacePage from "./CustomersWorkspacePage";

vi.mock("../../services/customerProfileApi", () => ({
  customerProfilesApi: { list: vi.fn(), register: vi.fn(), update: vi.fn(), get: vi.fn(), deactivate: vi.fn() },
}));
vi.mock("../../services/contactApi", () => ({ contactsApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn() } }));

const PROFILE: CustomerProfile = {
  id: "p1",
  organization_id: "org-1",
  contact_id: "c1",
  is_active: true,
  customer_notes: "Prefers weekend visits",
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
  contact: { id: "c1", first_name: "Asha", last_name: "Rao", email: "asha@example.com", phone: "+1 555 0100", is_active: true },
};

const INACTIVE: CustomerProfile = {
  ...PROFILE,
  id: "p2",
  contact_id: "c2",
  is_active: false,
  customer_notes: null,
  contact: { ...PROFILE.contact, id: "c2", first_name: "Ben", last_name: "Ortiz", email: null, phone: null, is_active: false },
};

const SESSION: AppContextValue = {
  user: { id: "alice", email: "alice@example.com", display_name: "Alice" },
  organizations: [{ id: "org-1", name: "Acme" }],
  selectedOrganization: { id: "org-1", name: "Acme" },
  status: "authenticated",
  error: null,
  selectOrganization: vi.fn(),
  refreshOrganizations: vi.fn(async () => undefined),
  refreshSession: vi.fn(async () => undefined),
  signOut: vi.fn(async () => undefined),
};

function renderPage() {
  return render(
    <AppContext.Provider value={SESSION}>
      <CustomersWorkspacePage />
    </AppContext.Provider>,
  );
}

describe("CustomersWorkspacePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1200 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 600 });
    vi.mocked(customerProfilesApi.list).mockImplementation(async (params = {}) => {
      const items = params.is_active === false ? [INACTIVE] : [PROFILE];
      return { items, page: 1, page_size: 100, total: items.length, total_pages: 1 };
    });
    vi.mocked(customerProfilesApi.update).mockReset();
    vi.mocked(contactsApi.list).mockResolvedValue({ items: [], page: 1, page_size: 100, total: 0, total_pages: 1 });
  });

  it("lists all customers by default, with no filter applied", async () => {
    renderPage();
    expect(await screen.findByText("Asha Rao")).toBeTruthy();
    expect(screen.getByText("Ben Ortiz")).toBeTruthy();
    expect(screen.queryByText(/active/i, { selector: ".df-grid-filter-chip *" })).toBeNull();
    expect(screen.getByRole("button", { name: "Filter" })).toBeTruthy();
  });

  it("filters by status through the optional Filter builder and removes the filter from its chip", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const builder = screen.getByRole("dialog", { name: "Filter records" });
    fireEvent.click(within(builder).getByRole("button", { name: "Add filter" }));
    fireEvent.change(within(builder).getByLabelText("Field for filter 1"), { target: { value: "status" } });
    fireEvent.change(within(builder).getByLabelText("Value for filter 1"), { target: { value: "inactive" } });
    fireEvent.click(within(builder).getByRole("button", { name: "Apply" }));
    expect(screen.queryByText("Asha Rao")).toBeNull();
    expect(screen.getByText("Ben Ortiz")).toBeTruthy();
    const chips = screen.getByLabelText("Active filters");
    expect(within(chips).getByText("Status is Inactive")).toBeTruthy();
    fireEvent.click(within(chips).getByRole("button", { name: "Remove filter Status is Inactive" }));
    expect(screen.getByText("Asha Rao")).toBeTruthy();
  });

  it("shows the Apply error when a filter has no value, and does not apply it", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const builder = screen.getByRole("dialog", { name: "Filter records" });
    fireEvent.click(within(builder).getByRole("button", { name: "Add filter" }));
    fireEvent.click(within(builder).getByRole("button", { name: "Apply" }));
    expect(within(builder).getByRole("alert").textContent).toContain("Choose a value for every filter");
  });

  it("opens the customer detail and saves the customer notes", async () => {
    vi.mocked(customerProfilesApi.update).mockResolvedValue({ ...PROFILE, customer_notes: "Prefers evenings" });
    renderPage();
    fireEvent.click(await screen.findByText("Asha Rao"));
    const dialog = screen.getByRole("dialog", { name: "Asha Rao" });
    fireEvent.change(within(dialog).getByLabelText("Customer notes"), { target: { value: "Prefers evenings" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save notes" }));
    await waitFor(() => expect(customerProfilesApi.update).toHaveBeenCalledWith("p1", { customer_notes: "Prefers evenings" }));
  });

  it("keeps Register disabled when there is no active contact to register", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: "Register customer" }));
    const dialog = screen.getByRole("dialog", { name: "Register a customer" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Register customer" })).toHaveProperty("disabled", true));
  });
});
