import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { contactsApi, type Contact } from "../../services/contactApi";
import { leadsApi, type Lead } from "../../services/leadApi";
import { teamApi } from "../../services/teamApi";
import PipelineWorkspacePage from "./PipelineWorkspacePage";

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

const ACTIVE_LEAD: Lead = {
  id: "l1",
  organization_id: "org-1",
  contact_id: "c1",
  status: "QUALIFIED",
  interest: "MEDIUM",
  outcome: null,
  owner_user_id: null,
  next_action: "Send brochure",
  next_action_at: null,
  is_active: true,
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
};

const INACTIVE_LEAD: Lead = { ...ACTIVE_LEAD, id: "l2", status: "NEW", is_active: false, next_action: null };

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
      <PipelineWorkspacePage />
    </AppContext.Provider>,
  );
}

describe("PipelineWorkspacePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1200 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 600 });
    vi.mocked(contactsApi.list).mockResolvedValue({ items: [ASHA], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(leadsApi.list).mockResolvedValue({
      items: [ACTIVE_LEAD, INACTIVE_LEAD],
      page: 1,
      page_size: 100,
      total: 2,
      total_pages: 1,
    });
    vi.mocked(teamApi.listMembers).mockRejectedValue(new Error("forbidden"));
  });

  it("shows active leads by default, with the stage and next action", async () => {
    renderPage();
    expect(await screen.findByText("Asha Rao")).toBeTruthy();
    expect(screen.getAllByText("Qualified").length).toBeGreaterThan(0);
    expect(screen.getByText("Send brochure")).toBeTruthy();
    expect(screen.getAllByText("Asha Rao")).toHaveLength(1);
  });

  it("includes inactive leads when the visibility filter is set to all", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    fireEvent.change(screen.getByRole("combobox", { name: "Lead visibility" }), { target: { value: "all" } });
    expect(await screen.findAllByText("Asha Rao")).toHaveLength(2);
  });

  it("switches to the board view and back to the list", async () => {
    renderPage();
    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(screen.getByRole("button", { name: "Board" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(await screen.findByText("Asha Rao")).toBeTruthy();
  });
});
