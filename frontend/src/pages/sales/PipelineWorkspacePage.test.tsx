import { fireEvent, render, screen, within } from "@testing-library/react";
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

  it("opens as a Kanban board with one column per stage and the lead as a card", async () => {
    renderPage();
    expect((await screen.findAllByRole("button", { name: /Asha Rao/ })).length).toBe(2);
    expect(screen.getByRole("listitem", { name: /Qualified: 1 lead/ })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: /New: 1 lead/ })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: /Won: 0 leads/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "List" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Board" })).toBeNull();
  });

  it("shows empty-stage states for stages without leads", async () => {
    renderPage();
    await screen.findAllByRole("button", { name: /Asha Rao/ });
    const won = screen.getByRole("listitem", { name: /Won: 0 leads/ });
    expect(within(won).getByText("No leads in this stage")).toBeTruthy();
  });

  it("filters cards by lead activity through the optional Filter builder", async () => {
    renderPage();
    expect(await screen.findAllByRole("button", { name: /Asha Rao/ })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const builder = screen.getByRole("dialog", { name: "Filter records" });
    fireEvent.click(within(builder).getByRole("button", { name: "Add filter" }));
    fireEvent.change(within(builder).getByLabelText("Field for filter 1"), { target: { value: "active" } });
    fireEvent.change(within(builder).getByLabelText("Value for filter 1"), { target: { value: "inactive" } });
    fireEvent.click(within(builder).getByRole("button", { name: "Apply" }));
    expect(screen.getAllByRole("button", { name: /Asha Rao/ })).toHaveLength(1);
  });
});
