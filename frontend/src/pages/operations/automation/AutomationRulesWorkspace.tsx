import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../../components/grid/gridLayout";
import type { GridFilterField } from "../../../components/grid/gridFilters";
import { RecordDialog, RecordProperty } from "../../../components/record/RecordDialog";
import { Badge, Button, useConfirmation } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { automationRulesApi, type AutomationExecution, type AutomationRule, type AutomationRuleStatus } from "../../../services/automationRuleApi";
import { teamApi } from "../../../services/teamApi";
import { formatDateTime, formatShortDate, fetchAllPages } from "../../sales/sales-shared";
import "../../sales/sales.css";
import "../documents/documents.css";
import "../../../components/record/nested-records.css";
import "./automation.css";
import { AutomationNav } from "./AutomationNav";
import { AutomationRuleEditor } from "./AutomationRuleEditor";
import {
  describeRule,
  eventTypeLabel,
  executionStatusLabel,
  executionStatusTone,
  ruleStatusLabel,
  ruleStatusTone,
} from "./automation-rule-model";

const PLANNED_CAPABILITIES: readonly { area: string; items: readonly string[] }[] = [
  { area: "Lead management", items: ["Lead assignment", "Follow-up reminders", "Lead status changes", "Unattended lead alerts"] },
  { area: "Customer engagement", items: ["Follow-up scheduling", "Customer activity reminders", "Site visit reminders", "Post-visit follow-ups"] },
  { area: "Property management", items: ["Property status changes", "Availability alerts", "Requirement matching triggers"] },
  { area: "Deal management", items: ["Deal stage transitions", "Payment milestone reminders", "Agreement and document reminders", "Commission workflow triggers"] },
  { area: "Operations", items: ["Task assignment", "Approval workflows", "Escalations", "Scheduled operational reminders"] },
];

const COLUMNS: GridColumnDef[] = [
  { key: "name", label: "Rule", defaultWidth: 280, primary: true },
  { key: "trigger", label: "Trigger", defaultWidth: 200 },
  { key: "action", label: "Action", defaultWidth: 240 },
  { key: "conditions", label: "Conditions", defaultWidth: 110 },
  { key: "status", label: "Status", defaultWidth: 130 },
  { key: "last", label: "Last run", defaultWidth: 190 },
  { key: "owner", label: "Owner", defaultWidth: 170 },
  { key: "updated", label: "Updated", defaultWidth: 130 },
  { key: "created", label: "Created", defaultWidth: 130, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  {
    key: "status",
    label: "Status",
    type: "select",
    options: [
      { value: "ACTIVE", label: "Active" },
      { value: "DRAFT", label: "Draft" },
      { value: "DISABLED", label: "Disabled" },
    ],
  },
];

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Check your connection and try again.";
}

interface WorkspaceData {
  rules: AutomationRule[];
  executions: AutomationExecution[];
  executionsTruncated: boolean;
  owners: ReadonlyMap<string, string>;
}

async function loadWorkspace(): Promise<WorkspaceData> {
  const [rules, executionPage, members] = await Promise.all([
    fetchAllPages((page) => automationRulesApi.list({ page, page_size: 100 })),
    automationRulesApi.listExecutions({ page: 1, page_size: 100 }),
    teamApi.listMembers().catch(() => []),
  ]);
  return {
    rules,
    executions: executionPage.items,
    executionsTruncated: executionPage.total > executionPage.items.length,
    owners: new Map(members.map((member) => [member.user_id, member.display_name || member.email])),
  };
}

/** The most recent execution for each rule, from the executions the server returned. */
function latestByRule(executions: readonly AutomationExecution[]): Map<string, AutomationExecution> {
  const latest = new Map<string, AutomationExecution>();
  for (const execution of executions) {
    const current = latest.get(execution.rule_id);
    const time = new Date(execution.started_at ?? execution.created_at).getTime();
    const currentTime = current ? new Date(current.started_at ?? current.created_at).getTime() : -Infinity;
    if (!current || time > currentTime) latest.set(execution.rule_id, execution);
  }
  return latest;
}

/**
 * The automation workspace. It shows what the rules do in plain language, when each last ran and how it ended, and who owns it.
 * Only the supported trigger and action are configurable; the other automation ideas are listed as planned, not as controls.
 */
export default function AutomationRulesWorkspace() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [data, setData] = useState<WorkspaceData>({ rules: [], executions: [], executionsTruncated: false, owners: new Map() });
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ rule: AutomationRule | null } | null>(null);

  const reload = useCallback(async () => {
    try {
      setData(await loadWorkspace());
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
    loadWorkspace()
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

  const latest = useMemo(() => latestByRule(data.executions), [data.executions]);
  const counts = useMemo(() => {
    const byStatus = { ACTIVE: 0, DRAFT: 0, DISABLED: 0 } as Record<AutomationRuleStatus, number>;
    for (const rule of data.rules) byStatus[rule.status] += 1;
    const failed = data.executions.filter((execution) => execution.status === "FAILED").length;
    return { ...byStatus, failed };
  }, [data]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return data.rules;
    return data.rules.filter((rule) => [rule.name, rule.description ?? "", describeRule(rule).action].some((value) => value.toLowerCase().includes(needle)));
  }, [data.rules, search]);

  const ownerOf = useCallback((rule: AutomationRule) => (rule.created_by_user_id ? (data.owners.get(rule.created_by_user_id) ?? "Unknown user") : "Not recorded"), [data.owners]);

  const sortValue = useCallback(
    (rule: AutomationRule, key: string): string | number | null => {
      switch (key) {
        case "trigger":
          return describeRule(rule).trigger;
        case "action":
          return describeRule(rule).action;
        case "conditions":
          return rule.conditions.length;
        case "status":
          return ruleStatusLabel(rule.status);
        case "last": {
          const run = latest.get(rule.id);
          return run ? new Date(run.started_at ?? run.created_at).getTime() : null;
        }
        case "owner":
          return ownerOf(rule);
        case "updated":
          return new Date(rule.updated_at).getTime();
        case "created":
          return new Date(rule.created_at).getTime();
        default:
          return rule.name;
      }
    },
    [latest, ownerOf],
  );

  const renderCell = useCallback(
    (rule: AutomationRule, key: string) => {
      const description = describeRule(rule);
      switch (key) {
        case "trigger":
          return description.trigger;
        case "action":
          return description.action;
        case "conditions":
          return rule.conditions.length === 0 ? "None" : `${rule.conditions.length}`;
        case "status":
          return <Badge tone={ruleStatusTone(rule.status)}>{ruleStatusLabel(rule.status)}</Badge>;
        case "last": {
          const run = latest.get(rule.id);
          if (!run) return <span className="df-sales-muted">No runs yet</span>;
          return (
            <span className="df-sales-stack">
              <Badge tone={executionStatusTone(run.status)}>{executionStatusLabel(run.status)}</Badge>
              <span className="df-sales-muted">{formatDateTime(run.started_at ?? run.created_at)}</span>
            </span>
          );
        }
        case "owner":
          return ownerOf(rule);
        case "updated":
          return formatShortDate(rule.updated_at);
        case "created":
          return formatShortDate(rule.created_at);
        default:
          return (
            <span className="df-sales-stack">
              <strong className="df-sales-primary">{rule.name}</strong>
              <span className="df-sales-muted">{rule.description || description.trigger}</span>
            </span>
          );
      }
    },
    [latest, ownerOf],
  );

  const filterValue = useCallback((rule: AutomationRule, key: string): string | null => (key === "status" ? rule.status : null), []);

  const selected = selectedId ? (data.rules.find((rule) => rule.id === selectedId) ?? null) : null;

  return (
    <div className="df-sales-page df-ops-page">
      <AutomationNav current="rules" />

      <section className="df-ops-intro" aria-label="Automation overview">
        <div>
          <p className="df-ops-eyebrow">Operations</p>
          <h1 className="df-ops-title">Automation</h1>
          <p className="df-sales-muted">Rules that react to business events and do the routine follow-up for you. Each run is recorded, so you can see what happened.</p>
        </div>
        <Button variant="primary" onClick={() => setEditor({ rule: null })}>
          New rule
        </Button>
      </section>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <dl className="df-nested-summary" aria-label="Automation totals">
        <div className="df-nested-summary-tile">
          <dt>Active rules</dt>
          <dd>{counts.ACTIVE}</dd>
        </div>
        <div className="df-nested-summary-tile">
          <dt>Drafts</dt>
          <dd>{counts.DRAFT}</dd>
        </div>
        <div className="df-nested-summary-tile">
          <dt>Disabled</dt>
          <dd>{counts.DISABLED}</dd>
        </div>
        <div className={`df-nested-summary-tile${counts.failed > 0 ? " df-nested-summary-tile--attention" : ""}`}>
          <dt>Failed runs (latest {data.executions.length})</dt>
          <dd>{counts.failed}</dd>
        </div>
      </dl>

      <div className="df-ops-two-column">
        <section className="df-ops-section" aria-labelledby="automation-supported-title">
          <h2 id="automation-supported-title" className="df-sales-section-title">
            What you can automate today
          </h2>
          <ul className="df-ops-list">
            <li>
              <strong>Trigger:</strong> a deal is created.
            </li>
            <li>
              <strong>Conditions:</strong> optional checks on the deal's stage, value, currency, owner, lead, customer, property and notes.
            </li>
            <li>
              <strong>Action:</strong> create a follow-up after a set number of days.
            </li>
          </ul>
          <p className="df-field-helper">A rule starts as a draft. Activate it when it is ready; the server checks the rule before it runs.</p>
        </section>

        <section className="df-ops-section" aria-labelledby="automation-planned-title">
          <h2 id="automation-planned-title" className="df-sales-section-title">
            Planned, not available yet
          </h2>
          {PLANNED_CAPABILITIES.map((group) => (
            <div key={group.area} className="df-ops-planned">
              <p className="df-ops-planned-area">{group.area}</p>
              <p className="df-sales-muted">{group.items.join(" · ")}</p>
            </div>
          ))}
          <p className="df-field-helper">These are not controls yet. They will appear here as they become available.</p>
        </section>
      </div>

      <EnterpriseDataGrid<AutomationRule>
        gridId="automation-rules"
        ariaLabel="Automation rules"
        columns={COLUMNS}
        rows={rows}
        rowKey={(rule) => rule.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search rules"
        searchPlaceholder="Search rule name, description or action"
        emptyTitle="No automation rules yet"
        emptyMessage="Create a rule to follow up automatically when a new deal comes in. It starts as a draft until you activate it."
        noMatchTitle="No rules match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel="New rule"
        onCreate={() => setEditor({ rule: null })}
        onOpenRow={(rule) => setSelectedId(rule.id)}
        onRefresh={() => {
          setStatus("loading");
          void reload();
        }}
        totalCount={data.rules.length}
        rangeLabel={search ? "Filtered" : "All rules shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {data.executionsTruncated ? (
        <p className="df-field-helper">Last-run information uses the latest {data.executions.length} runs.</p>
      ) : null}

      {selected ? (
        <RuleDetailDialog
          key={selected.id}
          rule={selected}
          owner={ownerOf(selected)}
          runs={data.executions.filter((execution) => execution.rule_id === selected.id)}
          onClose={() => setSelectedId(null)}
          onEdit={() => {
            setEditor({ rule: selected });
          }}
          onChanged={(message) => {
            setNotice(message);
            void reload();
          }}
        />
      ) : null}

      {editor ? (
        <AutomationRuleEditor
          rule={editor.rule}
          onClose={() => setEditor(null)}
          onSaved={(message) => {
            setEditor(null);
            setSelectedId(null);
            setNotice(message);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

interface RuleDetailDialogProps {
  rule: AutomationRule;
  owner: string;
  runs: readonly AutomationExecution[];
  onClose: () => void;
  onEdit: () => void;
  onChanged: (message: string) => void;
}

function RuleDetailDialog({ rule, owner, runs, onClose, onEdit, onChanged }: RuleDetailDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, confirmDialog] = useConfirmation();
  const description = describeRule(rule);
  const canActivate = rule.status !== "ACTIVE";

  async function changeStatus() {
    if (busy) return;
    if (rule.status === "ACTIVE") {
      const confirmed = await confirm(`"${rule.name}" will stop creating follow-ups for new deals until it is activated again.`, {
        title: "Disable rule?",
        confirmLabel: "Disable rule",
        tone: "danger",
      });
      if (!confirmed) return;
    }
    setBusy(true);
    setError("");
    try {
      if (rule.status === "ACTIVE") {
        await automationRulesApi.disable(rule.id);
        onChanged(`"${rule.name}" was disabled.`);
      } else {
        await automationRulesApi.activate(rule.id);
        onChanged(`"${rule.name}" is active. It will run when a matching deal is created.`);
      }
    } catch (changeError) {
      setError(errorText(changeError));
    } finally {
      setBusy(false);
    }
  }

  const main = (
    <div className="df-ops-detail">
      <section className="df-ops-section" aria-labelledby="rule-config-title">
        <h3 id="rule-config-title" className="df-sales-section-title">
          Configuration
        </h3>
        <dl className="df-nested-card-meta">
          <div>
            <dt>Trigger</dt>
            <dd>{description.trigger}</dd>
          </div>
          <div>
            <dt>Conditions</dt>
            <dd>{description.conditions.length === 0 ? "Runs for every new deal" : description.conditions.join("; ")}</dd>
          </div>
          <div>
            <dt>Action</dt>
            <dd>{description.action}</dd>
          </div>
        </dl>
        {rule.description ? <p className="df-ops-prewrap">{rule.description}</p> : null}
      </section>

      <section className="df-ops-section" aria-labelledby="rule-runs-title">
        <h3 id="rule-runs-title" className="df-sales-section-title">
          Recent runs
        </h3>
        {runs.length === 0 ? (
          <p className="df-sales-muted">This rule has not run yet. It runs when a matching deal is created while the rule is active.</p>
        ) : (
          <ul className="df-nested-list" aria-label="Recent runs of this rule">
            {runs.slice(0, 10).map((run) => (
              <li key={run.id} className="df-nested-card-meta">
                <span>
                  <Badge tone={executionStatusTone(run.status)}>{executionStatusLabel(run.status)}</Badge>{" "}
                  <span className="df-sales-muted">{formatDateTime(run.started_at ?? run.created_at)}</span>
                </span>
                <span>{eventTypeLabel(run.event_type)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="df-field-helper">Open Activity for the full record of each run and the reason for any failure.</p>
      </section>

      {error ? (
        <p className="df-sales-form-message df-sales-form-message--error" role="alert">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </div>
  );

  const aside = (
    <dl className="df-sales-properties">
      <RecordProperty label="Status">
        <Badge tone={ruleStatusTone(rule.status)}>{ruleStatusLabel(rule.status)}</Badge>
      </RecordProperty>
      <RecordProperty label="Owner">{owner}</RecordProperty>
      <RecordProperty label="Created">{formatDateTime(rule.created_at)}</RecordProperty>
      <RecordProperty label="Last updated">{formatDateTime(rule.updated_at)}</RecordProperty>
    </dl>
  );

  return (
    <RecordDialog
      open
      onClose={onClose}
      eyebrow="Automation rule"
      title={rule.name}
      closeLabel="Close rule details"
      busy={busy}
      main={main}
      aside={aside}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <Button variant="secondary" onClick={onEdit} disabled={busy}>
            Edit rule
          </Button>
          <Button variant={canActivate ? "primary" : "secondary"} onClick={() => void changeStatus()} loading={busy} disabled={busy}>
            {canActivate ? "Activate rule" : "Disable rule"}
          </Button>
        </>
      }
    />
  );
}
