import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { contactsApi, type Contact } from "../../services/contactApi";
import { leadsApi, type Lead } from "../../services/leadApi";
import { teamApi } from "../../services/teamApi";
import LeadsWorkspacePage from "./LeadsWorkspacePage";

vi.mock("../../services/contactApi", () => ({ contactsApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn() } }));
vi.mock("../../services/leadApi", () => ({ leadsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() } }));
vi.mock("../../services/teamApi", () => ({ teamApi: { listMembers: vi.fn() } }));
vi.mock("../../services/followUpApi", () => ({ followUpsApi: { list: vi.fn(async () => []) } }));

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

const LEAD: Lead = {
  id: "l1",
  organization_id: "org-1",
  contact_id: "c1",
  status: "NEW",
  interest: "HIGH",
  outcome: null,
  owner_user_id: null,
  next_action: null,
  next_action_at: null,
  is_active: true,
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
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
      <LeadsWorkspacePage />
    </AppContext.Provider>,
  );
}

describe("LeadsWorkspacePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1200 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 600 });
    vi.mocked(contactsApi.list).mockResolvedValue({ items: [ASHA], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(leadsApi.list).mockResolvedValue({ items: [LEAD], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(teamApi.listMembers).mockRejectedValue(new Error("forbidden"));
    vi.mocked(leadsApi.update).mockReset();
  });

  it("lists leads with the contact name and stage", async () => {
    renderPage();
    expect(await screen.findByText("Asha Rao")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New lead" })).toBeTruthy();
  });

  it("moves a lead to an allowed stage from its detail dialog", async () => {
    vi.mocked(leadsApi.update).mockResolvedValue({ ...LEAD, status: "ON_HOLD" });
    renderPage();
    fireEvent.click(await screen.findByText("Asha Rao"));
    const dialog = screen.getByRole("dialog", { name: "Asha Rao" });
    fireEvent.change(within(dialog).getByLabelText("Stage"), { target: { value: "ON_HOLD" } });
    await waitFor(() => expect(leadsApi.update).toHaveBeenCalledWith("l1", { status: "ON_HOLD" }));
  });

  it("asks for a next action before moving a lead into a key stage", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("Asha Rao"));
    const dialog = screen.getByRole("dialog", { name: "Asha Rao" });
    fireEvent.change(within(dialog).getByLabelText("Stage"), { target: { value: "QUALIFIED" } });
    expect(leadsApi.update).not.toHaveBeenCalled();
    const prompt = within(dialog).getByRole("form", { name: "Next action required" });
    fireEvent.click(within(prompt).getByRole("button", { name: "Save and move stage" }));
    expect(within(prompt).getByText("Enter the next action before continuing.")).toBeTruthy();
  });
});
