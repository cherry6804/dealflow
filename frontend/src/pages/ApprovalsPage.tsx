import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import {
  humanTaskApi,
  type HumanTask,
  type HumanTaskDetail,
  type HumanTaskStatus,
} from "../services/humanTaskApi";
import "./ApprovalsPage.css";

type Filter = "open" | "all";

const STATUS_LABEL: Record<HumanTaskStatus, string> = {
  pending: "Waiting for a decision",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
  expired: "Expired",
};

const EVENT_LABEL: Record<string, string> = {
  created: "Requested",
  assigned: "Assigned",
  reassigned: "Reassigned",
  comment: "Comment",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
  expired: "Expired",
};

const REASON_MESSAGE: Record<string, string> = {
  self_approval_refused: "The member who asked for this decision cannot decide it.",
  already_decided: "This task was already decided. The first decision stands.",
  task_expired: "This task expired before a decision was made.",
  permission_denied: "You do not hold the permission this task needs.",
  membership_inactive: "Your membership in this organization is not active.",
  not_assignee: "This task is assigned to another member.",
  task_not_found: "This task is not available to you.",
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "You do not have access to approvals in this organization.";
    const detail = error.details as { detail?: { reason?: string; problems?: string[] } } | undefined;
    const inner = detail?.detail;
    if (inner?.reason && REASON_MESSAGE[inner.reason]) return REASON_MESSAGE[inner.reason];
    if (inner?.problems?.length) return inner.problems.join(" ");
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

function formatTime(value: string | null): string {
  if (!value) return "No due time";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "No due time" : parsed.toLocaleString();
}

export default function ApprovalsPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const [tasks, setTasks] = useState<HumanTask[] | null>(null);
  const [selected, setSelected] = useState<HumanTaskDetail | null>(null);
  const [comment, setComment] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadTasks = useCallback(async (nextFilter: Filter) => {
    setLoadError(null);
    try {
      const response = await humanTaskApi.list(nextFilter === "open" ? "pending" : undefined);
      setTasks(response.items);
    } catch (caught) {
      setTasks([]);
      setLoadError(messageFor(caught));
    }
  }, []);

  useEffect(() => {
    void loadTasks(filter);
  }, [filter, loadTasks]);

  async function openTask(taskId: string) {
    setActionError(null);
    setNotice(null);
    setComment("");
    try {
      setSelected(await humanTaskApi.get(taskId));
    } catch (caught) {
      setActionError(messageFor(caught));
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      const result = await humanTaskApi.decide(selected.id, decision, comment);
      setNotice(result.changed ? "Your decision was recorded." : "This decision was already recorded.");
      setSelected(await humanTaskApi.get(selected.id));
      setComment("");
      await loadTasks(filter);
    } catch (caught) {
      setActionError(messageFor(caught));
      await loadTasks(filter);
    } finally {
      setBusy(false);
    }
  }

  async function addComment() {
    if (!selected || !comment.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      setSelected(await humanTaskApi.comment(selected.id, comment.trim()));
      setComment("");
    } catch (caught) {
      setActionError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  const isPending = selected?.status === "pending";

  return (
    <main className="approvals-page">
      <header className="approvals-header">
        <h1>Approvals</h1>
        <p className="approvals-subtle">
          Decisions that a workflow is waiting on. Each decision applies to the exact action shown, and a rejected or expired
          decision never lets the action run.
        </p>
      </header>

      <div className="approvals-layout">
        <section className="approvals-list" aria-labelledby="approvals-list-title">
          <div className="approvals-row">
            <h2 id="approvals-list-title">Tasks</h2>
            <label>
              Show
              <select value={filter} onChange={(event) => setFilter(event.target.value as Filter)}>
                <option value="open">Waiting for a decision</option>
                <option value="all">All</option>
              </select>
            </label>
          </div>

          {loadError ? <p role="alert" className="approvals-alert">{loadError}</p> : null}
          {tasks === null ? <p className="approvals-subtle">Loading approvals…</p> : null}
          {tasks !== null && tasks.length === 0 && !loadError ? (
            <p className="approvals-subtle">No approvals to show.</p>
          ) : null}

          {tasks && tasks.length > 0 ? (
            <ul className="approvals-items">
              {tasks.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    className="approvals-item"
                    aria-current={selected?.id === task.id ? "true" : undefined}
                    onClick={() => void openTask(task.id)}
                  >
                    <span className="approvals-item-title">{task.title}</span>
                    <span className="approvals-subtle">
                      {STATUS_LABEL[task.status]} · Due {formatTime(task.due_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <section className="approvals-detail" aria-labelledby="approvals-detail-title">
          <h2 id="approvals-detail-title">Decision</h2>
          {actionError ? <p role="alert" className="approvals-alert">{actionError}</p> : null}
          {notice ? <p role="status" className="approvals-notice">{notice}</p> : null}

          {!selected ? (
            <p className="approvals-subtle">Choose an approval to see what it asks and its history.</p>
          ) : (
            <>
              <h3>{selected.title}</h3>
              <p>{STATUS_LABEL[selected.status]}</p>
              {selected.instructions ? <p>{selected.instructions}</p> : null}
              <dl className="approvals-facts">
                <dt>Needs permission</dt>
                <dd>{selected.required_permission}</dd>
                <dt>Due</dt>
                <dd>{formatTime(selected.due_at)}</dd>
                {selected.decided_at ? (
                  <>
                    <dt>Decided</dt>
                    <dd>{formatTime(selected.decided_at)}</dd>
                  </>
                ) : null}
              </dl>

              {isPending ? (
                <div className="approvals-row">
                  <button type="button" className="approvals-button" disabled={busy} onClick={() => void decide("approve")}>
                    Approve
                  </button>
                  <button type="button" className="approvals-button" disabled={busy} onClick={() => void decide("reject")}>
                    Reject
                  </button>
                </div>
              ) : (
                <p className="approvals-subtle">This approval is closed. It cannot be decided again.</p>
              )}

              <label className="approvals-field">
                Comment
                <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} maxLength={1000} />
              </label>
              {isPending ? (
                <button type="button" className="approvals-button" disabled={busy || !comment.trim()} onClick={() => void addComment()}>
                  Add comment
                </button>
              ) : null}

              <h3>History</h3>
              <ol className="approvals-history">
                {selected.events.map((event) => (
                  <li key={event.id}>
                    <strong>{EVENT_LABEL[event.event_type] ?? event.event_type}</strong>
                    <span className="approvals-subtle"> {formatTime(event.created_at)}</span>
                    {event.comment ? <p>{event.comment}</p> : null}
                  </li>
                ))}
              </ol>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
