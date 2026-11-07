import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { contactsApi, type Contact } from "../../services/contactApi";
import ContactsWorkspacePage from "./ContactsWorkspacePage";

vi.mock("../../services/contactApi", () => ({
  contactsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  },
}));

const ASHA: Contact = {
  id: "c1",
  organization_id: "org-1",
  first_name: "Asha",
  last_name: "Rao",
  email: "asha@example.com",
  phone: "+1 555 0100",
  is_active: true,
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
};

const BEN: Contact = {
  ...ASHA,
  id: "c2",
  first_name: "Ben",
  last_name: "Ortiz",
  email: "ben@example.com",
  phone: null,
  is_active: false,
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
      <ContactsWorkspacePage />
    </AppContext.Provider>,
  );
}

describe("ContactsWorkspacePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(contactsApi.list).mockResolvedValue({ items: [ASHA, BEN], page: 1, page_size: 100, total: 2, total_pages: 1 });
    vi.mocked(contactsApi.create).mockReset();
    vi.mocked(contactsApi.update).mockReset();
  });

  it("loads the contacts from the existing list endpoint and shows the record count", async () => {
    renderPage();
    expect(await screen.findByText("Asha Rao")).toBeTruthy();
    expect(screen.getByText("Ben Ortiz")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(contactsApi.list).toHaveBeenCalledWith({ page: 1, page_size: 100 });
  });

  it("filters the grid with a single search field", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    const search = screen.getByRole("searchbox", { name: "Search contacts" });
    fireEvent.change(search, { target: { value: "ben@" } });
    expect(screen.queryByText("Asha Rao")).toBeNull();
    expect(screen.getByText("Ben Ortiz")).toBeTruthy();
  });

  it("opens the record detail when a row is clicked, with the editable fields and the status", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("Asha Rao"));
    const dialog = screen.getByRole("dialog", { name: "Asha Rao" });
    expect(within(dialog).getByLabelText(/First name/)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Deactivate contact" })).toBeTruthy();
  });

  it("requires a first name before creating a contact, and creates through the existing API", async () => {
    vi.mocked(contactsApi.create).mockResolvedValue({ ...ASHA, id: "c3", first_name: "Chen", last_name: null });
    renderPage();
    await screen.findByText("Asha Rao");

    fireEvent.click(screen.getByRole("button", { name: "New contact" }));
    const form = screen.getByRole("dialog", { name: "New contact" });
    fireEvent.click(within(form).getByRole("button", { name: "Save contact" }));
    expect(within(form).getByText("First name is required.")).toBeTruthy();
    expect(contactsApi.create).not.toHaveBeenCalled();

    fireEvent.change(within(form).getByLabelText(/First name/), { target: { value: "Chen" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save contact" }));
    await waitFor(() => expect(contactsApi.create).toHaveBeenCalledWith({ first_name: "Chen", last_name: null, email: null, phone: null }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "New contact" })).toBeNull());
  });

  it("shows a validation message for an incomplete email and does not send it", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: "New contact" }));
    const form = screen.getByRole("dialog", { name: "New contact" });
    fireEvent.change(within(form).getByLabelText(/First name/), { target: { value: "Dee" } });
    fireEvent.change(within(form).getByLabelText("Email address"), { target: { value: "dee@" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save contact" }));
    expect(within(form).getByText(/Enter a complete email/)).toBeTruthy();
    expect(contactsApi.create).not.toHaveBeenCalled();
  });
});
