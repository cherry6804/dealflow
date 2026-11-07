import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workflowApi, type WorkflowDetail } from "../services/workflowApi";
import WorkflowsPage from "./WorkflowsPage";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";


/** The pages link between automation sections, so they render inside a router as they do in the app. */
function renderWithRouter(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

vi.mock("../services/workflowApi", () => ({
  workflowApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    saveDraft: vi.fn(),
    validate: vi.fn(),
    publish: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    archive: vi.fn(),
    rollback: vi.fn(),
    versions: vi.fn(),
    history: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
    startRun: vi.fn(),
    cancelRun: vi.fn(),
    retryRun: vi.fn(),
    decideStep: vi.fn(),
    templates: vi.fn(),
    createFromTemplate: vi.fn(),
    simulate: vi.fn(),
  },
}));

const detail: WorkflowDetail = {
  id: "wf-1",
  name: "Lead follow-up",
  description: null,
  status: "draft",
  revision: 3,
  current_version_id: null,
  updated_at: null,
  draft: {
    category: "sales",
    purpose: "Score a lead.",
    trigger: { type: "manual" },
    inputs: [{ name: "lead_id", type: "uuid", required: true }],
    entry: "score",
    steps: [
      {
        id: "score",
        type: "crm_action",
        action: "lead.calculate_priority",
        arguments: { lead_id: "$input.lead_id" },
        next: "wait",
      },
      { id: "wait", type: "delay", seconds: 60 },
    ],
    limits: { max_steps: 5, max_duration_seconds: 600, max_concurrent_runs: 1, max_runs_per_hour: 10 },
    metadata: { labels: [] },
  },
  has_unpublished_changes: true,
  current_version: null,
};

describe("WorkflowsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workflowApi.list).mockResolvedValue({
      items: [{ id: "wf-1", name: "Lead follow-up", description: null, status: "draft", revision: 3, current_version_id: null, updated_at: null }],
    });
    vi.mocked(workflowApi.get).mockResolvedValue(detail);
    vi.mocked(workflowApi.versions).mockResolvedValue({ items: [] });
    vi.mocked(workflowApi.history).mockResolvedValue({ items: [] });
    vi.mocked(workflowApi.listRuns).mockResolvedValue({ items: [] });
    vi.mocked(workflowApi.templates).mockResolvedValue({
      items: [{ key: "new_lead", title: "New lead", description: "When a lead is created." }],
      catalogue: {
        step_types: ["crm_action", "condition", "agent", "approval", "delay"],
        crm_actions: ["lead.calculate_priority"],
        approver_permissions: ["leads.update"],
        trigger_events: ["lead.created"],
        condition_operators: ["eq"],
        categories: ["sales"],
      },
    });
  });

  it("lists workflows with their status and opens a draft", async () => {
    const user = userEvent.setup();
    renderWithRouter(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Lead follow-up/ }));
    expect(await screen.findByRole("heading", { name: "Lead follow-up" })).toBeTruthy();
    expect(screen.getByText(/draft has unpublished changes/)).toBeTruthy();
    expect(screen.getByText(/No published version yet/)).toBeTruthy();
  });

  it("shows each validation problem with the path it refers to", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.validate).mockResolvedValue({
      valid: false,
      revision: 3,
      problems: [{ path: "steps[0].action", message: "Must be an approved CRM action." }],
    });
    renderWithRouter(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Lead follow-up/ }));
    await user.click(await screen.findByRole("button", { name: "Validate" }));

    const list = await screen.findByLabelText("Validation problems");
    expect(list.textContent).toContain("steps[0].action");
    expect(list.textContent).toContain("Must be an approved CRM action.");
  });

  it("saves the draft with the revision it was based on and the step configuration", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.saveDraft).mockResolvedValue(detail);
    renderWithRouter(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Lead follow-up/ }));
    await screen.findByRole("heading", { name: "Definition" });
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(workflowApi.saveDraft).toHaveBeenCalledTimes(1));
    const [id, input] = vi.mocked(workflowApi.saveDraft).mock.calls[0];
    expect(id).toBe("wf-1");
    expect(input.revision).toBe(3);
    expect(input.configuration?.steps?.[0]).toMatchObject({
      id: "score",
      type: "crm_action",
      action: "lead.calculate_priority",
      arguments: { lead_id: "$input.lead_id" },
      next: "wait",
    });
  });

  it("refuses to save an argument block that is not a JSON object and says why", async () => {
    const user = userEvent.setup();
    renderWithRouter(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Lead follow-up/ }));
    const argumentsBox = await screen.findByLabelText(/Arguments \(JSON of references/);
    fireEvent.change(argumentsBox, { target: { value: "[1, 2]" } });
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByText("Step score arguments must be a JSON object.")).toBeTruthy();
    expect(workflowApi.saveDraft).not.toHaveBeenCalled();
  });
});
