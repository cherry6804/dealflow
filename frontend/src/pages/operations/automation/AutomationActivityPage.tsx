import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../../components/grid/gridLayout";
import type { GridFilterField } from "../../../components/grid/gridFilters";
import { RecordDialog, RecordProperty } from "../../../components/record/RecordDialog";
import { Badge, Button } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { automationRulesApi, type AutomationExecution, type AutomationExecutionStatus, type AutomationRule } from "../../../services/automationRuleApi";
import { dealsApi, type Deal } from "../../../services/dealApi";
import { customerProfilesApi, type CustomerProfile } from "../../../services/customerProfileApi";
import { propertiesApi, type Property } from "../../../services/propertyApi";
import { dealCustomerName, dealPropertyTitle } from "../../deals/deal-workflow";
import { fetchAllPages, formatDateTime, SALES_PAGE_SIZE } from "../../sales/sales-shared";
import "../../sales/sales.css";
import "../documents/documents.css";
import "../../../components/record/nested-records.css";
import "./automation.css";
import { AutomationNav } from "./AutomationNav";
import {
  actionOutcomes,
  eventTypeLabel,
  executionStatusLabel,
  executionStatusTone,
  failureReason,
  RETRY_UNAVAILABLE_NOTE,
} from "./automation-rule-model";

const STATUSES: readonly AutomationExecutionStatus[] = ["FAILED", "PARTIAL", "SUCCEEDED", "SKIPPED", "RUNNING", "PENDING"];
const MAX_RUNS = 500;

const COLUMNS: GridColumnDef[] = [
  { key: "started", label: "Started", defaultWidth: 180, primary: true },
  { key: "rule", label: "Rule", defaultWidth: 240 },
  { key: "trigger", label: "Trigger", defaultWidth: 140 },
  { key: "record", label: "Record", defaultWidth: 240 },
  { key: "status", label: "Result", defaultWidth: 160 },
  { key: "actions", label: "Actions", defaultWidth: 200 },
  { key: "duration", label: "Duration", defaultWidth: 120, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  { key: "status", label: "Result", type: "select", options: STATUSES.map((value) => ({ value, label: executionStatusLabel(value) })) },
];

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Check your connection and try again.";
}

function formatDuration(run: AutomationExecution): string {
  if (!run.started_at) return "Not started";
  const start = new Date(run.started_at).getTime();
  const end = run.completed_at ? new Date(run.completed_at).getTime() : run.status === "RUNNING" ? Date.now() : null;
  if (end === null || !Number.isFinite(start) || end < start) return "—";
  const milliseconds = end - start;
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`;
  return `${Math.floor(milliseconds / 60_000)} min ${Math.floor((milliseconds % 60_000) / 1000)} s`;
}

interface ActivityData {
  runs: AutomationExecution[];
  truncated: boolean;
  rules: ReadonlyMap<string, string>;
  deals: ReadonlyMap<string, string>;
}

async function loadActivity(): Promise<ActivityData> {
  // Runs are read page by page up to a fixed cap, so a very long history is shown as the latest runs, and the page says so.
  const runs: AutomationExecution[] = [];
  let totalPages = 1;
  let totalRuns = 0;
  for (let page = 1; page <= totalPages && runs.length < MAX_RUNS; page += 1) {
    const response = await automationRulesApi.listExecutions({ page, page_size: 100 });
    runs.push(...response.items);
    totalPages = response.total_pages;
    totalRuns = response.total;
  }
  const [rules, deals, customers, properties] = await Promise.all([
    fetchAllPages((page) => automationRulesApi.list({ page, page_size: 100 })),
    fetchAllPages((page) => dealsApi.list({ page, page_size: SALES_PAGE_SIZE })).catch(() => [] as Deal[]),
    fetchAllPages((page) => customerProfilesApi.list({ page, page_size: SALES_PAGE_SIZE })).catch(() => [] as CustomerProfile[]),
    fetchAllPages((page) => propertiesApi.search({ page, page_size: SALES_PAGE_SIZE })).catch(() => [] as Property[]),
  ]);
  const customerById = new Map(customers.map((customer) => [customer.id, customer]));
  const propertyById = new Map(properties.map((property) => [property.id, property]));
  return {
    runs,
    truncated: runs.length < totalRuns,
    rules: new Map(rules.map((rule: AutomationRule) => [rule.id, rule.name])),
    deals: new Map(
      deals.map((deal) => [deal.id, `${dealCustomerName(customerById.get(deal.customer_profile_id))} · ${dealPropertyTitle(propertyById.get(deal.property_id))}`]),
    ),
  };
}

/**
 * Automation activity: every run the server recorded, with what triggered it, the record it concerned, what each action did, and why
 * it failed where the server says so. Runs are never reconstructed or guessed, and a run cannot be retried from here.
 */
export default function AutomationActivityPage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [data, setData] = useState<ActivityData>({ runs: [], truncated: false, rules: new Map(), deals: new Map() });
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setData(await loadActivity());
      setLoadError("");
      setStatus("ready");
    } catch (error) {
      setLoadError(errorText(error));
      setStatus("error");
    }
  }, []);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    loadActivity()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setLoadError("");
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(errorText(error));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const recordLabel = useCallback(
    (run: AutomationExecution) => {
      if (run.event_type === "DEAL_CREATED") return data.deals.get(run.event_id) ?? "Deal unavailable";
      return "Record not available";
    },
    [data.deals],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return data.runs;
    return data.runs.filter((run) => [data.rules.get(run.rule_id) ?? "", recordLabel(run), eventTypeLabel(run.event_type)].some((value) => value.toLowerCase().includes(needle)));
  }, [data.runs, data.rules, recordLabel, search]);

  const sortValue = useCallback(
    (run: AutomationExecution, key: string): string | number | null => {
      switch (key) {
        case "rule":
          return data.rules.get(run.rule_id) ?? null;
        case "trigger":
          return eventTypeLabel(run.event_type);
        case "record":
          return recordLabel(run);
        case "status":
          return executionStatusLabel(run.status);
        case "actions":
          return run.action_results.length;
        case "duration":
          return run.started_at && run.completed_at ? new Date(run.completed_at).getTime() - new Date(run.started_at).getTime() : null;
        default:
          return new Date(run.started_at ?? run.created_at).getTime();
      }
    },
    [data.rules, recordLabel],
  );

  const renderCell = useCallback(
    (run: AutomationExecution, key: string) => {
      switch (key) {
        case "rule":
          return data.rules.get(run.rule_id) ?? "Rule unavailable";
        case "trigger":
          return eventTypeLabel(run.event_type);
        case "record":
          return recordLabel(run);
        case "status":
          return (
            <span className="df-sales-stack">
              <Badge tone={executionStatusTone(run.status)}>{executionStatusLabel(run.status)}</Badge>
              {failureReason(run) ? <span className="df-sales-muted">{failureReason(run)}</span> : null}
            </span>
          );
        case "actions": {
          const outcomes = actionOutcomes(run.action_results);
          return outcomes.length === 0 ? "None recorded" : outcomes.map((item) => item.label).join(", ");
        }
        case "duration":
          return formatDuration(run);
        default:
          return (
            <span className="df-sales-stack">
              <strong className="df-sales-primary">{formatDateTime(run.started_at ?? run.created_at)}</strong>
              <span className="df-sales-muted">{eventTypeLabel(run.event_type)}</span>
            </span>
          );
      }
    },
    [data.rules, recordLabel],
  );

  const filterValue = useCallback((run: AutomationExecution, key: string): string | null => (key === "status" ? run.status : null), []);

  const selected = selectedId ? (data.runs.find((run) => run.id === selectedId) ?? null) : null;

  return (
    <div className="df-sales-page df-ops-page">
      <AutomationNav current="activity" />

      <section className="df-ops-intro" aria-label="Automation activity">
        <div>
          <p className="df-ops-eyebrow">Operations</p>
          <h1 className="df-ops-title">Automation activity</h1>
          <p className="df-sales-muted">Each run of an automation rule, what triggered it, the record it concerned, and how it ended.</p>
        </div>
      </section>

      <EnterpriseDataGrid<AutomationExecution>
        gridId="automation-activity"
        ariaLabel="Automation runs"
        columns={COLUMNS}
        rows={rows}
        rowKey={(run) => run.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search runs"
        searchPlaceholder="Search rule, record or trigger"
        emptyTitle="No automation runs yet"
        emptyMessage="Runs appear here after an active rule is triggered by a new deal."
        noMatchTitle="No runs match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        onOpenRow={(run) => setSelectedId(run.id)}
        onRefresh={() => {
          setStatus("loading");
          void reload();
        }}
        totalCount={data.runs.length}
        rangeLabel={data.truncated ? `Latest ${data.runs.length} runs` : "All runs shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {selected ? (
        <RunDetailDialog
          run={selected}
          ruleName={data.rules.get(selected.rule_id) ?? "Rule unavailable"}
          recordName={recordLabel(selected)}
          onClose={() => setSelectedId(null)}
        />
      ) : null}
    </div>
  );
}

function RunDetailDialog({ run, ruleName, recordName, onClose }: { run: AutomationExecution; ruleName: string; recordName: string; onClose: () => void }) {
  const outcomes = actionOutcomes(run.action_results);
  const reason = failureReason(run);

  const main = (
    <div className="df-ops-detail">
      <section className="df-ops-section" aria-labelledby="run-trigger-title">
        <h3 id="run-trigger-title" className="df-sales-section-title">
          What triggered it
        </h3>
        <p>
          <strong>{eventTypeLabel(run.event_type)}</strong> · {recordName}
        </p>
        <p className="df-sales-muted">Rule: {ruleName}</p>
      </section>

      <section className="df-ops-section" aria-labelledby="run-actions-title">
        <h3 id="run-actions-title" className="df-sales-section-title">
          Actions
        </h3>
        {outcomes.length === 0 ? (
          <p className="df-sales-muted">No action results were recorded for this run.</p>
        ) : (
          <ul className="df-ops-list" aria-label="Action results">
            {outcomes.map((item, index) => (
              <li key={`${item.type}-${index}`}>
                <strong>{item.label}</strong>{" "}
                <Badge tone={item.succeeded === true ? "success" : item.succeeded === false ? "danger" : "neutral"}>
                  {item.succeeded === true ? "Succeeded" : item.succeeded === false ? "Failed" : "No result recorded"}
                </Badge>
                {item.detail ? <span className="df-sales-muted"> · {item.detail}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="df-ops-section" aria-labelledby="run-outcome-title">
        <h3 id="run-outcome-title" className="df-sales-section-title">
          Outcome
        </h3>
        {reason ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {reason}
          </p>
        ) : (
          <p className="df-sales-muted">{run.status === "SUCCEEDED" ? "The run completed without errors." : "No reason was recorded for this result."}</p>
        )}
        <p className="df-field-helper">{RETRY_UNAVAILABLE_NOTE}</p>
      </section>
    </div>
  );

  const aside = (
    <dl className="df-sales-properties">
      <RecordProperty label="Result">
        <Badge tone={executionStatusTone(run.status)}>{executionStatusLabel(run.status)}</Badge>
      </RecordProperty>
      <RecordProperty label="Started">{formatDateTime(run.started_at)}</RecordProperty>
      <RecordProperty label="Completed">{formatDateTime(run.completed_at)}</RecordProperty>
      <RecordProperty label="Duration">{formatDuration(run)}</RecordProperty>
      <RecordProperty label="Reference">
        <span className="df-ops-prewrap">{run.id}</span>
      </RecordProperty>
    </dl>
  );

  return (
    <RecordDialog
      open
      onClose={onClose}
      eyebrow="Automation run"
      title={ruleName}
      closeLabel="Close run details"
      main={main}
      aside={aside}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      }
    />
  );
}
