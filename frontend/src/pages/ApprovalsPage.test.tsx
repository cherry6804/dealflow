import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";
import { humanTaskApi, type HumanTask, type HumanTaskDetail } from "../services/humanTaskApi";
import ApprovalsPage from "./ApprovalsPage";

vi.mock("../services/humanTaskApi", () => ({
  humanTaskApi: {
    list: vi.fn(),
    get: vi.fn(),
    decide: vi.fn(),
    comment: vi.fn(),
    cancel: vi.fn(),
  },
}));

const pending: HumanTask = {
  id: "task-1",
  kind: "approval",
  status: "pending",
  title: "Approve step score",
  instructions: "Decide whether this workflow run may continue.",
  required_permission: "leads.update",
  assigned_to_user_id: null,
  requested_by_user_id: "user-2",
  decided_by_user_id: null,
  decided_at: null,
  decision_comment: null,
  due_at: "2030-01-01T10:00:00Z",
  version: 1,
  workflow_execution_id: "run-1",
  workflow_step_id: "score",
  created_at: "2029-12-31T10:00:00Z",
  updated_at: "2029-12-31T10:00:00Z",
};

const detail: HumanTaskDetail = {
  ...pending,
  events: [
    {
      id: "event-1",
      event_type: "created",
      actor_user_id: "user-2",
      from_user_id: null,
      to_user_id: null,
      comment: null,
      created_at: "2029-12-31T10:00:00Z",
    },
  ],
};

const closed: HumanTaskDetail = {
  ...pending,
  status: "approved",
  decided_by_user_id: "user-3",
  decided_at: "2030-01-01T09:00:00Z",
  events: detail.events,
};

describe("ApprovalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists tasks and opens one with its decision controls and history", async () => {
    vi.mocked(humanTaskApi.list).mockResolvedValue({ items: [pending] });
    vi.mocked(humanTaskApi.get).mockResolvedValue(detail);
    render(<ApprovalsPage />);

    const item = await screen.findByRole("button", { name: /Approve step score/ });
    await userEvent.click(item);

    expect(await screen.findByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
    expect(screen.getByText("Requested")).toBeTruthy();
    expect(humanTaskApi.list).toHaveBeenCalledWith("pending");
  });

  it("shows the empty state when nothing needs a decision", async () => {
    vi.mocked(humanTaskApi.list).mockResolvedValue({ items: [] });
    render(<ApprovalsPage />);

    expect(await screen.findByText("No approvals to show.")).toBeTruthy();
  });

  it("explains an access refusal without showing any task", async () => {
    vi.mocked(humanTaskApi.list).mockRejectedValue(new ApiError("Forbidden", 403, {}));
    render(<ApprovalsPage />);

    expect((await screen.findByRole("alert")).textContent).toContain("You do not have access to approvals");
  });

  it("records an approval with the comment and reloads the decided task", async () => {
    vi.mocked(humanTaskApi.list).mockResolvedValue({ items: [pending] });
    vi.mocked(humanTaskApi.get).mockResolvedValueOnce(detail).mockResolvedValueOnce(closed);
    vi.mocked(humanTaskApi.decide).mockResolvedValue({ ...closed, changed: true });
    render(<ApprovalsPage />);

    await userEvent.click(await screen.findByRole("button", { name: /Approve step score/ }));
    await userEvent.type(await screen.findByLabelText("Comment"), "Looks right.");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(humanTaskApi.decide).toHaveBeenCalledWith("task-1", "approve", "Looks right."));
    expect((await screen.findByRole("status")).textContent).toContain("Your decision was recorded.");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Approve" })).toBeNull());
    expect(screen.getByText("This approval is closed. It cannot be decided again.")).toBeTruthy();
  });

  it("shows the refusal reason when a decision is refused", async () => {
    vi.mocked(humanTaskApi.list).mockResolvedValue({ items: [pending] });
    vi.mocked(humanTaskApi.get).mockResolvedValue(detail);
    vi.mocked(humanTaskApi.decide).mockRejectedValue(
      new ApiError("Conflict", 409, { detail: { reason: "already_decided" } }),
    );
    render(<ApprovalsPage />);

    await userEvent.click(await screen.findByRole("button", { name: /Approve step score/ }));
    const detailPanel = screen.getByRole("heading", { name: "Decision" }).closest("section") as HTMLElement;
    await userEvent.click(within(detailPanel).getByRole("button", { name: "Reject" }));

    expect((await screen.findByRole("alert")).textContent).toContain("This task was already decided.");
  });
});
