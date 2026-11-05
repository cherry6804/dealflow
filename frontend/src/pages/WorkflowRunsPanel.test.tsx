import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workflowApi, type WorkflowRun } from "../services/workflowApi";
import WorkflowRunsPanel from "./WorkflowRunsPanel";

vi.mock("../services/workflowApi", () => ({
  workflowApi: {
    listRuns: vi.fn(),
    getRun: vi.fn(),
    startRun: vi.fn(),
    cancelRun: vi.fn(),
    retryRun: vi.fn(),
    decideStep: vi.fn(),
  },
}));

const waiting: WorkflowRun = {
  id: "run-1",
  workflow_id: "wf-1",
  status: "waiting_approval",
  version_id: "v-1",
  version_number: 2,
  trigger: { type: "manual", event: null, event_key: null, source_execution_id: null },
  retry_of_execution_id: null,
  run_as_user_id: "u-1",
  initiated_by_user_id: "u-1",
  failure_reason: null,
  steps_completed: 1,
  next_step_id: "ask",
  created_at: "2030-01-10T12:00:00+00:00",
  started_at: null,
  finished_at: null,
  deadline_at: null,
  output: null,
  steps: [{ step_id: "score", step_index: 0, type: "crm_action", status: "succeeded", attempts: 1, reason_code: null,
    trace: null, wake_at: null, decided_at: null, finished_at: null }],
  pending_approval: { step_id: "ask", approver_permission: "leads.update", reason: "Confirm the lead." },
};

describe("WorkflowRunsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workflowApi.listRuns).mockResolvedValue({ items: [waiting] });
    vi.mocked(workflowApi.getRun).mockResolvedValue(waiting);
  });

  it("shows a waiting run with its recorded steps and the approval it needs", async () => {
    const user = userEvent.setup();
    render(<WorkflowRunsPanel workflowId="wf-1" canStart />);

    await user.click(await screen.findByRole("button", { name: /Version 2/ }));

    expect(await screen.findByText(/Approval needed for step ask/)).toBeTruthy();
    expect(screen.getByText(/requires leads.update/)).toBeTruthy();
    expect(screen.getByText(/score/)).toBeTruthy();
  });

  it("sends the approval decision with its reason", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.decideStep).mockResolvedValue({ ...waiting, status: "succeeded" });
    render(<WorkflowRunsPanel workflowId="wf-1" canStart />);

    await user.click(await screen.findByRole("button", { name: /Version 2/ }));
    const panel = (await screen.findByText(/Approval needed/)).closest("div") as HTMLElement;
    await user.type(within(panel).getByLabelText("Reason"), "Confirmed by phone");
    await user.click(within(panel).getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(workflowApi.decideStep).toHaveBeenCalledWith("run-1", "ask", "approve", "Confirmed by phone"));
  });

  it("starts a run with a parsed input and a fresh idempotency key", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.startRun).mockResolvedValue({ ...waiting, created: true });
    render(<WorkflowRunsPanel workflowId="wf-1" canStart />);

    await screen.findByText(/Version 2/);
    const input = screen.getByLabelText("Input (JSON object)");
    await user.clear(input);
    await user.click(input);
    await user.paste('{"lead_id":"abc"}');
    await user.click(screen.getByRole("button", { name: "Start a run" }));

    await waitFor(() => expect(workflowApi.startRun).toHaveBeenCalledTimes(1));
    const [id, body, key] = vi.mocked(workflowApi.startRun).mock.calls[0];
    expect(id).toBe("wf-1");
    expect(body).toEqual({ lead_id: "abc" });
    expect(key.startsWith("ui-")).toBe(true);
  });

  it("does not offer to start a run for an unpublished workflow", async () => {
    render(<WorkflowRunsPanel workflowId="wf-1" canStart={false} />);
    expect(await screen.findByText(/Publish the workflow and make sure it is active/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start a run" })).toBeNull();
  });
});
