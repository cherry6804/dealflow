import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workflowApi, type WorkflowDetail } from "../services/workflowApi";
import WorkflowCanvas from "./WorkflowCanvas";
import { connectionsFor } from "./workflowCanvasModel";
import WorkflowsPage from "./WorkflowsPage";

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

const gatedDetail: WorkflowDetail = {
  id: "wf-2",
  name: "Gated follow-up",
  description: null,
  status: "draft",
  revision: 7,
  current_version_id: null,
  updated_at: null,
  draft: {
    category: "sales",
    purpose: "Score a lead after approval.",
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
        timeout_seconds: 120,
        retry: { max_attempts: 2, backoff_seconds: 5 },
        on_failure: { policy: "route", route_to: "wait" },
        approval: { approver_permission: "leads.update", expires_after_seconds: 3600 },
      },
      { id: "wait", type: "delay", seconds: 60 },
    ],
    limits: { max_steps: 5, max_duration_seconds: 600, max_concurrent_runs: 1, max_runs_per_hour: 10 },
    metadata: { labels: [] },
  },
  has_unpublished_changes: true,
  current_version: null,
};

describe("workflow editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workflowApi.list).mockResolvedValue({
      items: [{ id: "wf-2", name: "Gated follow-up", description: null, status: "draft", revision: 7, current_version_id: null, updated_at: null }],
    });
    vi.mocked(workflowApi.get).mockResolvedValue(gatedDetail);
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

  it("keeps the approval gate, failure policy, retries and timeout when a draft is saved", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.saveDraft).mockResolvedValue(gatedDetail);
    render(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Gated follow-up/ }));
    await screen.findByRole("heading", { name: "Definition" });
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(workflowApi.saveDraft).toHaveBeenCalledTimes(1));
    const step = vi.mocked(workflowApi.saveDraft).mock.calls[0][1].configuration?.steps?.[0];
    expect(step).toMatchObject({
      approval: { approver_permission: "leads.update", expires_after_seconds: 3600 },
      on_failure: { policy: "route", route_to: "wait" },
      retry: { max_attempts: 2, backoff_seconds: 5 },
      timeout_seconds: 120,
    });
  });

  it("selects a node on the canvas and shows that step's settings", async () => {
    const user = userEvent.setup();
    render(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Gated follow-up/ }));
    const nodes = await screen.findAllByRole("button", { name: /CRM action/ });
    expect(nodes[0].getAttribute("aria-pressed")).toBe("false");
    await user.click(nodes[0]);
    expect(nodes[0].getAttribute("aria-pressed")).toBe("true");
    expect(document.getElementById("workflow-step-0")?.className).toContain("workflows-step-selected");
  });

  it("creates a draft from a template with the name given and never publishes it", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.createFromTemplate).mockResolvedValue({ id: "wf-3", name: "Pilot", status: "draft", revision: 1 });
    vi.mocked(workflowApi.get).mockResolvedValue({ ...gatedDetail, id: "wf-3", name: "Pilot" });
    render(<WorkflowsPage />);

    await user.selectOptions(await screen.findByLabelText("Start from"), "new_lead");
    await user.type(screen.getByLabelText("Name"), "Pilot");
    await user.click(screen.getByRole("button", { name: "Create draft" }));

    await waitFor(() => expect(workflowApi.createFromTemplate).toHaveBeenCalledWith("new_lead", "Pilot"));
    expect(workflowApi.create).not.toHaveBeenCalled();
    expect(workflowApi.publish).not.toHaveBeenCalled();
    expect(await screen.findByText(/Nothing runs until it is published/)).toBeTruthy();
  });

  it("simulates the draft for a sample input and shows the path without running it", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.simulate).mockResolvedValue({
      valid: true,
      problems: [],
      executed: false,
      revision: 7,
      plan_truncated: false,
      not_performed: ["CRM actions were not run and no CRM record was changed."],
      plan: [{ step_id: "score", type: "crm_action", branch: "main", outcome: "would_run", target: "lead.calculate_priority" }],
    });
    render(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Gated follow-up/ }));
    const sample = await screen.findByLabelText("Sample input (JSON object)");
    fireEvent.change(sample, { target: { value: '{"lead_id":"abc"}' } });
    await user.click(screen.getByRole("button", { name: "Simulate" }));

    await waitFor(() => expect(workflowApi.simulate).toHaveBeenCalledWith("wf-2", { lead_id: "abc" }));
    expect(await screen.findByText(/Simulation finished. Nothing was run./)).toBeTruthy();
    expect(screen.getByText(/would run/)).toBeTruthy();
    expect(screen.getByText("CRM actions were not run and no CRM record was changed.")).toBeTruthy();
  });

  it("refuses a sample input that is not a JSON object without calling the service", async () => {
    const user = userEvent.setup();
    render(<WorkflowsPage />);

    await user.click(await screen.findByRole("button", { name: /Gated follow-up/ }));
    fireEvent.change(await screen.findByLabelText("Sample input (JSON object)"), { target: { value: "[1]" } });
    await user.click(screen.getByRole("button", { name: "Simulate" }));

    expect(await screen.findByText("The sample input must be a JSON object.")).toBeTruthy();
    expect(workflowApi.simulate).not.toHaveBeenCalled();
  });

  it("describes a node's outgoing connections, and says when a node ends the run", () => {
    expect(connectionsFor({ id: "a", type: "crm_action", next: "b", then: "", elseStep: "" })).toEqual(["then: b"]);
    expect(connectionsFor({ id: "a", type: "delay", next: "", then: "", elseStep: "" })).toEqual(["ends the run"]);
    expect(connectionsFor({ id: "c", type: "condition", next: "", then: "x", elseStep: "" })).toEqual([
      "if true: x",
      "if false: not set",
    ]);
  });

  it("shows an empty canvas message when there are no steps", () => {
    render(<WorkflowCanvas nodes={[]} entry="" selectedIndex={null} onSelect={() => undefined} />);
    expect(screen.getByText("Add a step to see the workflow here.")).toBeTruthy();
  });
});
