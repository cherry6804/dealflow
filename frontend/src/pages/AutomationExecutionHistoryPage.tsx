
import { useCallback, useEffect, useState } from "react";

import {
  automationRulesApi,
  type AutomationExecution,
  type AutomationExecutionStatus,
} from "../services/automationRuleApi";

import "./AutomationExecutionHistoryPage.css";

const PAGE_SIZE = 10;

const EXECUTION_STATUSES: AutomationExecutionStatus[] = [
  "PENDING",
  "RUNNING",
  "SUCCEEDED",
  "PARTIAL",
  "FAILED",
  "SKIPPED",
];

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatDuration(execution: AutomationExecution): string {
  if (!execution.started_at) {
    return "Not started";
  }

  const start = new Date(execution.started_at).getTime();
  const end = execution.completed_at
    ? new Date(execution.completed_at).getTime()
    : execution.status === "RUNNING"
      ? Date.now()
      : null;

  if (!Number.isFinite(start) || end === null || end < start) {
    return "—";
  }

  const milliseconds = end - start;

  if (milliseconds < 1000) {
    return `${milliseconds} ms`;
  }

  if (milliseconds < 60_000) {
    return `${(milliseconds / 1000).toFixed(1)} sec`;
  }

  const minutes = Math.floor(milliseconds / 60_000);
  const seconds = Math.floor((milliseconds % 60_000) / 1000);

  return `${minutes} min ${seconds} sec`;
}

function statusLabel(status: AutomationExecutionStatus): string {
  switch (status) {
    case "PENDING":
      return "Pending";
    case "RUNNING":
      return "Running";
    case "SUCCEEDED":
      return "Succeeded";
    case "PARTIAL":
      return "Partially completed";
    case "FAILED":
      return "Failed";
    case "SKIPPED":
      return "Skipped";
  }
}

function statusClass(status: AutomationExecutionStatus): string {
  return `execution-status execution-status-${status.toLowerCase()}`;
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "No data";
  } catch {
    return String(value);
  }
}

function isActionResultRecord(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function AutomationExecutionHistoryPage() {
  const [executions, setExecutions] = useState<AutomationExecution[]>([]);
  const [statusFilter, setStatusFilter] = useState<
    "" | AutomationExecutionStatus
  >("");
  const [ruleIdFilter, setRuleIdFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadExecutions = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      setError(null);

      try {
        const response = await automationRulesApi.listExecutions({
          page: targetPage,
          page_size: PAGE_SIZE,
          ...(statusFilter ? { status: statusFilter } : {}),
          ...(ruleIdFilter.trim() ? { rule_id: ruleIdFilter.trim() } : {}),
          ...(eventTypeFilter.trim()
            ? { event_type: eventTypeFilter.trim() }
            : {}),
        });

        setExecutions(response.items);
        setTotal(response.total);
        setTotalPages(Math.max(1, response.total_pages));
        setPage(response.page);
        setExpandedId(null);
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to load automation execution history.",
        );
      } finally {
        setLoading(false);
      }
    },
    [eventTypeFilter, ruleIdFilter, statusFilter],
  );

  useEffect(() => {
    void loadExecutions(1);
  }, [loadExecutions]);

  const applyFilters = () => {
    void loadExecutions(1);
  };

  const clearFilters = () => {
    setStatusFilter("");
    setRuleIdFilter("");
    setEventTypeFilter("");
    setPage(1);
  };

  const goToPage = (targetPage: number) => {
    if (
      targetPage < 1 ||
      targetPage > totalPages ||
      targetPage === page ||
      loading
    ) {
      return;
    }

    void loadExecutions(targetPage);
  };

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

  return (
    <section className="execution-page">
      <header className="execution-header">
        <div>
          <span className="execution-eyebrow">AUTOMATION · OBSERVABILITY</span>
          <h1>Execution History</h1>
          <p>
            Inspect automation runs, review action results, and investigate
            failures across your workspace.
          </p>
        </div>

        <button
          className="execution-button execution-button-primary"
          type="button"
          onClick={() => void loadExecutions(page)}
          disabled={loading}
        >
          <span aria-hidden="true">↻</span>
          {loading ? "Refreshing…" : "Refresh history"}
        </button>
      </header>

      <section className="execution-summary" aria-label="History summary">
        <div className="execution-summary-card">
          <span className="execution-summary-icon" aria-hidden="true">
            ↗
          </span>
          <div>
            <span className="execution-summary-label">Matching executions</span>
            <strong>{total.toLocaleString("en-IN")}</strong>
          </div>
        </div>

        <div className="execution-summary-card">
          <span className="execution-summary-icon execution-summary-icon-blue">
            ◷
          </span>
          <div>
            <span className="execution-summary-label">Current page</span>
            <strong>
              {page} <small>of {totalPages}</small>
            </strong>
          </div>
        </div>
      </section>

      <section className="execution-panel">
        <div className="execution-panel-heading">
          <div>
            <h2>Execution records</h2>
            <p>
              Select a record to inspect its event, action results, and
              diagnostic details.
            </p>
          </div>
        </div>

        <div className="execution-filters">
          <label className="execution-filter">
            <span>Status</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(
                  event.target.value as "" | AutomationExecutionStatus,
                );
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {EXECUTION_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {statusLabel(status)}
                </option>
              ))}
            </select>
          </label>

          <label className="execution-filter">
            <span>Rule ID</span>
            <input
              value={ruleIdFilter}
              onChange={(event) => {
                setRuleIdFilter(event.target.value);
                setPage(1);
              }}
              placeholder="Filter by rule UUID"
              spellCheck={false}
            />
          </label>

          <label className="execution-filter">
            <span>Event type</span>
            <input
              value={eventTypeFilter}
              onChange={(event) => {
                setEventTypeFilter(event.target.value);
                setPage(1);
              }}
              placeholder="e.g. DEAL_CREATED"
            />
          </label>

          <div className="execution-filter-actions">
            <button
              className="execution-button execution-button-primary"
              type="button"
              onClick={applyFilters}
              disabled={loading}
            >
              Apply filters
            </button>
            <button
              className="execution-button execution-button-secondary"
              type="button"
              onClick={clearFilters}
              disabled={
                loading &&
                !statusFilter &&
                !ruleIdFilter &&
                !eventTypeFilter
              }
            >
              Clear
            </button>
          </div>
        </div>

        {error && (
          <div className="execution-alert" role="alert">
            <div>
              <strong>Could not load execution history</strong>
              <p>{error}</p>
            </div>
            <button
              type="button"
              onClick={() => void loadExecutions(page)}
              disabled={loading}
            >
              Try again
            </button>
          </div>
        )}

        {loading ? (
          <div className="execution-state" role="status" aria-live="polite">
            <span className="execution-spinner" aria-hidden="true" />
            <h3>Loading execution history</h3>
            <p>Retrieving audit records for your workspace.</p>
          </div>
        ) : !error && executions.length === 0 ? (
          <div className="execution-state">
            <span className="execution-empty-icon" aria-hidden="true">
              ◷
            </span>
            <h3>No execution records found</h3>
            <p>
              Automation runs will appear here when execution records exist.
              Try clearing your filters if you expected to see results.
            </p>
            <button
              className="execution-button execution-button-secondary"
              type="button"
              onClick={clearFilters}
            >
              Clear filters
            </button>
          </div>
        ) : !error ? (
          <>
            <div className="execution-table-wrap">
              <table className="execution-table">
                <thead>
                  <tr>
                    <th scope="col">Automation / event</th>
                    <th scope="col">Status</th>
                    <th scope="col">Started</th>
                    <th scope="col">Duration</th>
                    <th scope="col">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {executions.map((execution) => {
                    const expanded = expandedId === execution.id;

                    return (
                      <tr
                        key={execution.id}
                        className={expanded ? "execution-row-expanded" : ""}
                      >
                        <td colSpan={5} className="execution-record-cell">
                          <div className="execution-record">
                            <div className="execution-record-main">
                              <div className="execution-rule-id">
                                <span>Rule</span>
                                <code>{execution.rule_id}</code>
                              </div>
                              <div className="execution-event">
                                {execution.event_type || "Unknown event"}
                              </div>
                              <div className="execution-event-id">
                                Event ID: {execution.event_id || "—"}
                              </div>
                            </div>

                            <div className="execution-status-cell">
                              <span className={statusClass(execution.status)}>
                                <span
                                  className="execution-status-dot"
                                  aria-hidden="true"
                                />
                                {statusLabel(execution.status)}
                              </span>
                            </div>

                            <div className="execution-started">
                              {formatDate(
                                execution.started_at ?? execution.created_at,
                              )}
                            </div>

                            <div className="execution-duration">
                              {formatDuration(execution)}
                            </div>

                            <div className="execution-details-action">
                              <button
                                className="execution-text-button"
                                type="button"
                                aria-expanded={expanded}
                                aria-controls={`execution-details-${execution.id}`}
                                onClick={() =>
                                  setExpandedId(expanded ? null : execution.id)
                                }
                              >
                                {expanded ? "Hide details" : "View details"}
                              </button>
                            </div>
                          </div>

                          {expanded && (
                            <section
                              className="execution-details"
                              id={`execution-details-${execution.id}`}
                              aria-label="Execution details"
                            >
                              <div className="execution-details-heading">
                                <div>
                                  <h3>Execution details</h3>
                                  <p>
                                    Read-only audit record. Historical execution
                                    data cannot be edited here.
                                  </p>
                                </div>
                                <span className={statusClass(execution.status)}>
                                  {statusLabel(execution.status)}
                                </span>
                              </div>

                              <div className="execution-metadata-grid">
                                <div className="execution-metadata">
                                  <span>Execution ID</span>
                                  <code>{execution.id}</code>
                                </div>
                                <div className="execution-metadata">
                                  <span>Organization ID</span>
                                  <code>{execution.organization_id}</code>
                                </div>
                                <div className="execution-metadata">
                                  <span>Rule ID</span>
                                  <code>{execution.rule_id}</code>
                                </div>
                                <div className="execution-metadata">
                                  <span>Event ID</span>
                                  <code>{execution.event_id || "—"}</code>
                                </div>
                                <div className="execution-metadata">
                                  <span>Created</span>
                                  <strong>{formatDate(execution.created_at)}</strong>
                                </div>
                                <div className="execution-metadata">
                                  <span>Last updated</span>
                                  <strong>{formatDate(execution.updated_at)}</strong>
                                </div>
                                <div className="execution-metadata">
                                  <span>Started</span>
                                  <strong>{formatDate(execution.started_at)}</strong>
                                </div>
                                <div className="execution-metadata">
                                  <span>Completed</span>
                                  <strong>{formatDate(execution.completed_at)}</strong>
                                </div>
                              </div>

                              {execution.error_message && (
                                <div className="execution-error-detail">
                                  <strong>Failure / diagnostic message</strong>
                                  <p>{execution.error_message}</p>
                                </div>
                              )}

                              <div className="execution-json-section">
                                <h4>Action results</h4>
                                {Array.isArray(execution.action_results) &&
                                execution.action_results.length > 0 ? (
                                  <div className="execution-action-results">
                                    {execution.action_results.map(
                                      (result, index) => (
                                        <article
                                          className="execution-action-result"
                                          key={`${execution.id}-action-${index}`}
                                        >
                                          <div className="execution-action-result-heading">
                                            <strong>
                                              Action {index + 1}
                                            </strong>
                                            {isActionResultRecord(result) &&
                                              typeof result.status === "string" && (
                                                <span className="execution-action-result-status">
                                                  {result.status}
                                                </span>
                                              )}
                                          </div>
                                          <pre>{formatJson(result)}</pre>
                                        </article>
                                      ),
                                    )}
                                  </div>
                                ) : (
                                  <p className="execution-no-results">
                                    No action results were recorded for this
                                    execution.
                                  </p>
                                )}
                              </div>
                            </section>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <footer className="execution-pagination">
              <span>
                Showing {firstResult}–{lastResult} of{" "}
                {total.toLocaleString("en-IN")} executions
              </span>
              <div>
                <button
                  className="execution-button execution-button-secondary"
                  type="button"
                  onClick={() => goToPage(page - 1)}
                  disabled={loading || page <= 1}
                >
                  Previous
                </button>
                <span className="execution-page-count">
                  Page {page} of {totalPages}
                </span>
                <button
                  className="execution-button execution-button-secondary"
                  type="button"
                  onClick={() => goToPage(page + 1)}
                  disabled={loading || page >= totalPages}
                >
                  Next
                </button>
              </div>
            </footer>
          </>
        ) : null}
      </section>

      <p className="execution-footnote">
        <span aria-hidden="true">ⓘ</span>
        Execution history is scoped to the selected organization. Access is
        controlled by the backend permissions for automation records.
      </p>
    </section>
  );
}
