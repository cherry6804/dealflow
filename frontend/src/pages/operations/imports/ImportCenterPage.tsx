import { useCallback, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../../components/grid/gridLayout";
import { Badge, Button } from "../../../components/ui";
import { importApi } from "../../../services/importApi";
import { formatShortDate, formatDateTime } from "../../sales/sales-shared";
import "../../sales/sales.css";
import "../documents/documents.css";
import "../../../components/record/nested-records.css";
import "./imports.css";
import { ImportWizardDialog } from "./ImportWizardDialog";
import {
  countsFromResult,
  IMPORT_DATA_TYPES,
  IMPORT_MAX_FILE_SIZE_BYTES,
  importStatusLabel,
  importStatusTone,
  readImportHistory,
  upsertHistory,
  writeImportHistory,
  type ImportHistoryEntry,
} from "./import-workflow";

const COLUMNS: GridColumnDef[] = [
  { key: "file", label: "Source file", defaultWidth: 280, primary: true },
  { key: "type", label: "Data type", defaultWidth: 120 },
  { key: "status", label: "Status", defaultWidth: 200 },
  { key: "total", label: "Rows read", defaultWidth: 110 },
  { key: "successful", label: "Created", defaultWidth: 110 },
  { key: "failed", label: "Not imported", defaultWidth: 130 },
  { key: "skipped", label: "Skipped", defaultWidth: 100, defaultVisible: false },
  { key: "started", label: "Started", defaultWidth: 150 },
  { key: "completed", label: "Completed", defaultWidth: 150, defaultVisible: false },
  { key: "format", label: "Format", defaultWidth: 90, defaultVisible: false },
];

function refreshedEntry(entry: ImportHistoryEntry, saved: Awaited<ReturnType<typeof importApi.result>>): ImportHistoryEntry {
  return {
    ...entry,
    status: saved.status,
    counts: countsFromResult(saved),
    completedAt: entry.completedAt ?? (saved.status === "pending" ? null : new Date().toISOString()),
  };
}

/**
 * Import center. The API keeps no list of past imports, so the history here is the batches this browser started; each is read from
 * the server when it is refreshed or opened. Only contacts can be imported at the moment, and the other data types are shown as not
 * available rather than offered as controls.
 */
export default function ImportCenterPage() {
  const [history, setHistory] = useState<ImportHistoryEntry[]>(() => readImportHistory());
  const [wizardBatch, setWizardBatch] = useState<string | null | "new">(null);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState("");

  const [search, setSearch] = useState("");

  const persist = useCallback((next: ImportHistoryEntry[]) => {
    setHistory(next);
    writeImportHistory(next);
  }, []);

  // Uses the latest history, so entries written by an open wizard are never overwritten by a stale copy.
  const rememberEntry = useCallback((entry: ImportHistoryEntry) => {
    setHistory((current) => {
      const next = upsertHistory(current, entry);
      writeImportHistory(next);
      return next;
    });
  }, []);

  const visibleRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return history;
    return history.filter((entry) => `${entry.sourceFilename} ${entry.sourceFormat} ${entry.status}`.toLowerCase().includes(needle));
  }, [history, search]);

  const totals = useMemo(() => {
    const completed = history.filter((entry) => entry.status === "completed").length;
    const attention = history.filter((entry) => entry.status === "completed_with_errors" || entry.status === "failed").length;
    const created = history.reduce((sum, entry) => sum + (entry.counts?.successful ?? 0), 0);
    return { completed, attention, created };
  }, [history]);

  async function refreshAll() {
    if (refreshing || history.length === 0) return;
    setRefreshing(true);
    setNotice("");
    const settled = await Promise.allSettled(history.map((entry) => importApi.result(entry.batchId)));
    const failures = settled.filter((item) => item.status === "rejected").length;
    const next = history.map((entry, index) => {
      const outcome = settled[index];
      return outcome.status === "fulfilled" ? refreshedEntry(entry, outcome.value) : entry;
    });
    persist(next);
    setNotice(
      failures > 0
        ? `${failures} import(s) could not be read from the server. Their last known status is shown.`
        : "Import statuses are up to date.",
    );
    setRefreshing(false);
  }

  const sortValue = useCallback((entry: ImportHistoryEntry, key: string): string | number | null => {
    switch (key) {
      case "status":
        return importStatusLabel(entry.status);
      case "total":
        return entry.counts?.total ?? null;
      case "successful":
        return entry.counts?.successful ?? null;
      case "failed":
        return entry.counts?.failed ?? null;
      case "skipped":
        return entry.counts?.skipped ?? null;
      case "started":
        return new Date(entry.startedAt).getTime();
      case "completed":
        return entry.completedAt ? new Date(entry.completedAt).getTime() : null;
      case "format":
        return entry.sourceFormat;
      case "type":
        return "Contacts";
      default:
        return entry.sourceFilename;
    }
  }, []);

  const renderCell = useCallback((entry: ImportHistoryEntry, key: string) => {
    switch (key) {
      case "status":
        return <Badge tone={importStatusTone(entry.status)}>{importStatusLabel(entry.status)}</Badge>;
      case "type":
        return "Contacts";
      case "total":
        return entry.counts?.total ?? "—";
      case "successful":
        return entry.counts?.successful ?? "—";
      case "failed":
        return entry.counts?.failed ?? "—";
      case "skipped":
        return entry.counts?.skipped ?? "—";
      case "started":
        return formatDateTime(entry.startedAt);
      case "completed":
        return entry.completedAt ? formatDateTime(entry.completedAt) : "—";
      case "format":
        return entry.sourceFormat.toUpperCase();
      default:
        return (
          <span className="df-sales-stack">
            <strong className="df-sales-primary">{entry.sourceFilename}</strong>
            <span className="df-sales-muted">{formatShortDate(entry.startedAt)}</span>
          </span>
        );
    }
  }, []);

  const wizardOpen = wizardBatch !== null;

  return (
    <div className="df-sales-page df-ops-page">
      <h1 className="df-visually-hidden">Imports</h1>

      <section className="df-ops-intro" aria-label="Import summary">
        <div>
          <p className="df-ops-eyebrow">Operations</p>
          <h2 className="df-ops-title">Import center</h2>
          <p className="df-sales-muted">Bring contacts in from a spreadsheet or another system. Each file is checked before anything is created.</p>
        </div>
        <Button variant="primary" onClick={() => setWizardBatch("new")}>
          New import
        </Button>
      </section>

      <dl className="df-nested-summary" aria-label="Import totals on this device">
        <div className="df-nested-summary-tile">
          <dt>Imports started here</dt>
          <dd>{history.length}</dd>
        </div>
        <div className="df-nested-summary-tile">
          <dt>Completed</dt>
          <dd>{totals.completed}</dd>
        </div>
        <div className={`df-nested-summary-tile${totals.attention > 0 ? " df-nested-summary-tile--attention" : ""}`}>
          <dt>Need attention</dt>
          <dd>{totals.attention}</dd>
        </div>
        <div className="df-nested-summary-tile">
          <dt>Contacts created</dt>
          <dd>{totals.created}</dd>
        </div>
      </dl>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<ImportHistoryEntry>
        gridId="imports"
        ariaLabel="Import history"
        columns={COLUMNS}
        rows={visibleRows}
        rowKey={(entry) => entry.batchId}
        sortValue={sortValue}
        renderCell={renderCell}
        status="ready"
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search imports"
        searchPlaceholder="Search file name or status"
        emptyTitle="No imports started from this browser"
        emptyMessage="Start an import to see its status, counts and report here."
        noMatchTitle="No imports match"
        noMatchMessage="Try another search to see the other imports."
        createLabel="New import"
        onCreate={() => setWizardBatch("new")}
        onOpenRow={(entry) => setWizardBatch(entry.batchId)}
        onRefresh={() => void refreshAll()}
        totalCount={history.length}
        rangeLabel="Imports from this browser"
      />

      <section className="df-ops-section" aria-labelledby="import-types-title">
        <h3 id="import-types-title" className="df-sales-section-title">
          What can be imported
        </h3>
        <ul className="df-ops-type-list df-ops-type-list--compact">
          {IMPORT_DATA_TYPES.map((item) => (
            <li key={item.id} className="df-ops-type df-ops-type--static">
              <strong>{item.label}</strong>
              {item.available ? <Badge tone="success">Available</Badge> : <Badge tone="neutral">Not available yet</Badge>}
            </li>
          ))}
        </ul>
        <p className="df-field-helper">
          Files must be CSV or XLSX, up to {Math.round(IMPORT_MAX_FILE_SIZE_BYTES / (1024 * 1024))} MB. Rows that are invalid or duplicate an existing contact
          are reported and never created.
        </p>
      </section>

      {wizardOpen ? (
        <ImportWizardDialog
          key={wizardBatch}
          batchId={wizardBatch === "new" ? undefined : (wizardBatch ?? undefined)}
          onClose={() => setWizardBatch(null)}
          onChanged={rememberEntry}
        />
      ) : null}
    </div>
  );
}
