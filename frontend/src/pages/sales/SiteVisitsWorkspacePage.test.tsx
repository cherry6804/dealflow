import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { contactsApi, type Contact } from "../../services/contactApi";
import { customerProfilesApi } from "../../services/customerProfileApi";
import { leadsApi, type Lead } from "../../services/leadApi";
import { propertiesApi, type Property } from "../../services/propertyApi";
import { siteVisitsApi, type SiteVisit } from "../../services/siteVisitApi";
import { teamApi } from "../../services/teamApi";
import SiteVisitsWorkspacePage from "./SiteVisitsWorkspacePage";

vi.mock("../../services/contactApi", () => ({ contactsApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn() } }));
vi.mock("../../services/customerProfileApi", () => ({ customerProfilesApi: { list: vi.fn(), get: vi.fn(), register: vi.fn(), update: vi.fn(), deactivate: vi.fn() } }));
vi.mock("../../services/leadApi", () => ({ leadsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() } }));
vi.mock("../../services/propertyApi", () => ({ propertiesApi: { search: vi.fn() } }));
vi.mock("../../services/siteVisitApi", () => ({ siteVisitsApi: { list: vi.fn(), schedule: vi.fn(), recordAttendance: vi.fn() } }));
vi.mock("../../services/teamApi", () => ({ teamApi: { listMembers: vi.fn() } }));
vi.mock("../../services/followUpApi", () => ({ followUpsApi: { list: vi.fn(async () => []), createFromSiteVisit: vi.fn() } }));

const CONTACT: Contact = {
  id: "c1",
  organization_id: "org-1",
  first_name: "Asha",
  last_name: "Rao",
  email: "asha@example.com",
  phone: null,
  is_active: true,
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
};

const LEAD: Lead = {
  id: "l1",
  organization_id: "org-1",
  contact_id: "c1",
  status: "VISIT",
  interest: "HIGH",
  outcome: null,
  owner_user_id: null,
  next_action: null,
  next_action_at: null,
  is_active: true,
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
};

const PROPERTY = { id: "p1", address_line_1: "12 Lake Road", locality: null, city: "Pune" } as unknown as Property;

const VISIT: SiteVisit = {
  id: "v1",
  organization_id: "org-1",
  property_id: "p1",
  lead_id: "l1",
  customer_profile_id: null,
  owner_user_id: "alice",
  scheduled_at: "2026-02-10T10:00:00Z",
  ends_at: null,
  status: "SCHEDULED",
  outcome: null,
  notes: null,
  feedback: null,
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
  has_follow_up: false,
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
      <SiteVisitsWorkspacePage />
    </AppContext.Provider>,
  );
}

describe("SiteVisitsWorkspacePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1200 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 600 });
    vi.mocked(siteVisitsApi.list).mockResolvedValue({ items: [VISIT], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(propertiesApi.search).mockResolvedValue({ items: [PROPERTY], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(leadsApi.list).mockResolvedValue({ items: [LEAD], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(customerProfilesApi.list).mockResolvedValue({ items: [], page: 1, page_size: 100, total: 0, total_pages: 1 });
    vi.mocked(contactsApi.list).mockResolvedValue({ items: [CONTACT], page: 1, page_size: 100, total: 1, total_pages: 1 });
    vi.mocked(teamApi.listMembers).mockRejectedValue(new Error("forbidden"));
  });

  it("lists visits in the shared grid with the property, lead, status and no configuration column", async () => {
    renderPage();
    expect(await screen.findByText("12 Lake Road, Pune")).toBeTruthy();
    expect(screen.getByText("Asha Rao")).toBeTruthy();
    expect(screen.getByText("Scheduled")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Schedule visit" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Columns" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Configure columns" })).toBeNull();
  });

  it("opens the visit record and offers attendance, follow-up and history actions", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("12 Lake Road, Pune"));
    const dialog = screen.getByRole("dialog", { name: /Feb|2026|10/ });
    expect(within(dialog).getByRole("button", { name: "Record attendance" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Create follow-up" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "View visit history" })).toBeTruthy();
  });

  it("shows the no-match state with a clear-filters action when a filter hides every visit", async () => {
    renderPage();
    await screen.findByText("12 Lake Road, Pune");
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const builder = screen.getByRole("dialog", { name: "Filter records" });
    fireEvent.click(within(builder).getByRole("button", { name: "Add filter" }));
    fireEvent.change(within(builder).getByLabelText("Field for filter 1"), { target: { value: "status" } });
    fireEvent.change(within(builder).getByLabelText("Value for filter 1"), { target: { value: "COMPLETED" } });
    fireEvent.click(within(builder).getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("heading", { name: "No site visits match this search or filter" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Schedule visit" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("12 Lake Road, Pune")).toBeTruthy();
  });
});
