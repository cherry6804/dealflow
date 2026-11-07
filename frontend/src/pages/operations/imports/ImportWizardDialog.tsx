import { useEffect, useRef, useState } from "react";

import { Badge, Button, Dialog, useConfirmation } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { importApi, type ImportPreview, type ImportProcessingResult, type ImportResult, type ImportValidationErrorDetail, type ImportValidationResult } from "../../../services/importApi";
import {
  canConfirmImport,
  countsFromResult,
  groupErrors,
  hasRequiredMapping,
  IMPORT_ALLOWED_EXTENSIONS,
  IMPORT_DATA_TYPES,
  importStatusLabel,
  importStatusTone,
  rowsNotImported,
  validateImportFile,
  type ImportHistoryEntry,
} from "./import-workflow";

type Step = "type" | "upload" | "mapping" | "preview" | "validate" | "confirm" | "processing" | "report";

const STEPS: readonly { id: Step; label: string }[] = [
  { id: "type", label: "Data type" },
  { id: "upload", label: "Upload" },
  { id: "mapping", label: "Columns" },
  { id: "preview", label: "Preview" },
  { id: "validate", label: "Validate" },
  { id: "confirm", label: "Confirm" },
  { id: "report", label: "Report" },
];

const PREVIEW_ROWS_SHOWN = 10;

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

interface ImportWizardDialogProps {
  /** Opens a batch this browser started, in its report. Omit to start a new import. */
  batchId?: string;
  onClose: () => void;
  /** Called whenever the batch changes, so the history list stays current. */
  onChanged: (entry: ImportHistoryEntry) => void;
}

/**
 * Guided import. Each step asks the server for what it needs: the preview and validation do not change any data, and only the
 * confirm step creates contacts. A duplicate is reported and never created. The report separates rows that failed validation from
 * rows that failed while processing.
 */
export function ImportWizardDialog({ batchId: openBatchId, onClose, onChanged }: ImportWizardDialogProps) {
  const [step, setStep] = useState<Step>(openBatchId ? "report" : "type");
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<{ id: string; name: string; format: string; startedAt: string } | null>(
    openBatchId ? { id: openBatchId, name: "", format: "", startedAt: new Date().toISOString() } : null,
  );
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [validation, setValidation] = useState<ImportValidationResult | null>(null);
  const [processed, setProcessed] = useState<ImportProcessingResult | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [confirm, confirmDialog] = useConfirmation();
  const [reportLoading, setReportLoading] = useState(Boolean(openBatchId));

  // Opening a past batch loads its saved report. State is set only inside the request callbacks.
  useEffect(() => {
    if (!openBatchId) return;
    let cancelled = false;
    importApi
      .result(openBatchId)
      .then((saved) => {
        if (cancelled) return;
        setResult(saved);
        setBatch((current) => ({ id: openBatchId, name: saved.source_filename, format: saved.source_format, startedAt: current?.startedAt ?? new Date().toISOString() }));
        setReportLoading(false);
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(messageOf(loadError));
        setReportLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [openBatchId]);

  const currentIndex = STEPS.findIndex((item) => item.id === step);
  const isReport = step === "report";
  const reportCounts = result ? countsFromResult(result) : processed ? countsFromResult(processed) : null;
  const finished = Boolean(result || processed);

  function remember(status: string, counts: ImportHistoryEntry["counts"], completedAt: string | null) {
    if (!batch) return;
    onChanged({
      batchId: batch.id,
      sourceFilename: batch.name,
      sourceFormat: batch.format,
      startedAt: batch.startedAt,
      status,
      counts,
      completedAt,
    });
  }

  async function handleUpload() {
    if (inFlight.current || !file) return;
    const problem = validateImportFile(file);
    if (problem) {
      setError(problem);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const created = await importApi.upload(file);
      const startedAt = new Date().toISOString();
      setBatch({ id: created.id, name: created.source_filename, format: created.source_format, startedAt });
      // Remember the batch straight away, so a later failure still leaves it in this browser's history.
      onChanged({ batchId: created.id, sourceFilename: created.source_filename, sourceFormat: created.source_format, startedAt, status: "pending", counts: null, completedAt: null });
      const loaded = await importApi.preview(created.id);
      setPreview(loaded);
      setStep("mapping");
    } catch (uploadError) {
      setError(messageOf(uploadError));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function retryPreview() {
    if (inFlight.current || !batch) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setPreview(await importApi.preview(batch.id));
      setStep("mapping");
    } catch (previewError) {
      setError(messageOf(previewError));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function runValidation() {
    if (inFlight.current || !batch) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setValidation(await importApi.validate(batch.id));
    } catch (validationError) {
      // A mapping or file problem is shown as the server states it. Nothing has been imported.
      setValidation(null);
      setError(messageOf(validationError));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function runImport() {
    if (inFlight.current || !batch || !validation || processed || result) return;
    const confirmed = await confirm(
      `${validation.valid_rows} valid row(s) from "${batch.name}" will create contacts in this organization. ${rowsNotImported(validation)} row(s) will not be imported. This import runs once; it cannot be started again for this file.`,
      { title: `Import ${validation.valid_rows} contact(s)?`, confirmLabel: "Import contacts" },
    );
    if (!confirmed) return;

    inFlight.current = true;
    setBusy(true);
    setError("");
    setStep("processing");
    try {
      const outcome = await importApi.process(batch.id);
      setProcessed(outcome);
      const saved = await importApi.result(batch.id);
      setResult(saved);
      remember(saved.status, countsFromResult(saved), new Date().toISOString());
      setStep("report");
    } catch (processError) {
      // A batch that was already processed is not run again. Its saved report is shown instead.
      if (processError instanceof ApiError && processError.status === 409) {
        try {
          const saved = await importApi.result(batch.id);
          setResult(saved);
          remember(saved.status, countsFromResult(saved), new Date().toISOString());
          setStep("report");
          return;
        } catch (reportError) {
          setError(messageOf(reportError));
        }
      } else {
        setError(`${messageOf(processError)} The import did not finish. Check the report before trying again.`);
      }
      setStep("confirm");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function downloadReport() {
    if (!batch || busy) return;
    setBusy(true);
    setError("");
    try {
      await importApi.downloadErrors(batch.id);
    } catch (downloadError) {
      setError(messageOf(downloadError));
    } finally {
      setBusy(false);
    }
  }

  const grouped = groupErrors(validation?.errors ?? []);
  const processingErrors = result?.errors ?? processed?.errors ?? [];
  const canClose = !busy;

  return (
    <Dialog
      open
      onClose={onClose}
      title={batch ? (batch.name || "Import report") : "New import"}
      eyebrow="Import center · Contacts"
      closeLabel="Close import"
      size="lg"
      busy={busy}
      dirty={!finished && step !== "type" && !busy}
      footer={
        <>
          {step === "type" ? (
            <Button variant="secondary" onClick={onClose} disabled={!canClose}>
              Cancel
            </Button>
          ) : null}
          {step === "upload" ? (
            <>
              <Button variant="secondary" onClick={() => setStep("type")} disabled={busy}>
                Back
              </Button>
              <Button variant="primary" onClick={() => void handleUpload()} loading={busy} disabled={!file || busy}>
                Upload and read file
              </Button>
            </>
          ) : null}
          {step === "mapping" ? (
            <>
              <Button variant="secondary" onClick={() => setStep("upload")} disabled={busy}>
                Upload a different file
              </Button>
              <Button variant="primary" onClick={() => setStep("preview")} disabled={!preview || !hasRequiredMapping(preview)}>
                Continue to preview
              </Button>
            </>
          ) : null}
          {step === "preview" ? (
            <>
              <Button variant="secondary" onClick={() => setStep("mapping")}>
                Back
              </Button>
              <Button variant="primary" onClick={() => setStep("validate")}>
                Continue to validation
              </Button>
            </>
          ) : null}
          {step === "validate" ? (
            <>
              <Button variant="secondary" onClick={() => setStep("preview")} disabled={busy}>
                Back
              </Button>
              {validation ? (
                <Button variant="primary" onClick={() => setStep("confirm")} disabled={!canConfirmImport(validation, false)}>
                  Review import
                </Button>
              ) : (
                <Button variant="primary" onClick={() => void runValidation()} loading={busy} disabled={busy}>
                  Validate rows
                </Button>
              )}
            </>
          ) : null}
          {step === "confirm" ? (
            <>
              <Button variant="secondary" onClick={() => setStep("validate")} disabled={busy}>
                Back
              </Button>
              <Button variant="primary" onClick={() => void runImport()} disabled={busy || !validation || !canConfirmImport(validation, false)}>
                {validation ? `Import ${validation.valid_rows} contact(s)` : "Import"}
              </Button>
            </>
          ) : null}
          {step === "report" ? (
            <>
              {processingErrors.length > 0 || (result?.failed_rows ?? 0) > 0 ? (
                <Button variant="secondary" onClick={() => void downloadReport()} disabled={busy}>
                  Download error report
                </Button>
              ) : null}
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            </>
          ) : null}
        </>
      }
    >
      <ol className="df-ops-steps" aria-label="Import steps">
        {STEPS.map((item, index) => {
          const active = item.id === step;
          const done = index < currentIndex || (isReport && item.id !== "report" && finished);
          return (
            <li key={item.id} className={`df-ops-step${active ? " df-ops-step--active" : ""}${done ? " df-ops-step--done" : ""}`} aria-current={active ? "step" : undefined}>
              <span className="df-ops-step-index" aria-hidden="true">
                {done ? "✓" : index + 1}
              </span>
              <span>{item.label}</span>
            </li>
          );
        })}
      </ol>

      {error ? (
        <p className="df-sales-form-message df-sales-form-message--error" role="alert">
          {error}
        </p>
      ) : null}

      {step === "type" ? (
        <section aria-labelledby="import-type-title" className="df-ops-section">
          <h3 id="import-type-title" className="df-sales-section-title">
            What are you importing?
          </h3>
          <ul className="df-ops-type-list">
            {IMPORT_DATA_TYPES.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={`df-ops-type${item.id === "contacts" ? " df-ops-type--selected" : ""}`}
                  aria-pressed={item.id === "contacts"}
                  disabled={!item.available}
                  onClick={() => setStep("upload")}
                >
                  <strong>{item.label}</strong>
                  <span className="df-sales-muted">{item.description}</span>
                  {!item.available ? <Badge tone="neutral">Not available yet</Badge> : null}
                </button>
              </li>
            ))}
          </ul>
          <p className="df-field-helper">Only contacts can be imported at the moment. Each valid row creates one contact.</p>
        </section>
      ) : null}

      {step === "upload" ? (
        <section aria-labelledby="import-upload-title" className="df-ops-section">
          <h3 id="import-upload-title" className="df-sales-section-title">
            Upload the source file
          </h3>
          <label className="df-field">
            <span className="df-field-label">Source file</span>
            <input
              className="df-input"
              type="file"
              accept={IMPORT_ALLOWED_EXTENSIONS.join(",")}
              disabled={busy}
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setError("");
              }}
            />
            <span className="df-field-helper">CSV or XLSX, up to 10 MB. The first row must hold column headers, such as First name, Last name, Email and Phone.</span>
          </label>
          {file ? (
            <p className="df-sales-muted">
              {file.name} · {(file.size / 1024).toFixed(1)} KB
            </p>
          ) : null}
          <p className="df-field-helper">Uploading stores the file and reads it. No contacts are created until you confirm the import.</p>
          {batch && !preview ? (
            <div className="df-sales-form-actions">
              <p className="df-sales-muted">The file was stored but could not be read yet.</p>
              <Button variant="secondary" onClick={() => void retryPreview()} loading={busy} disabled={busy}>
                Read the stored file again
              </Button>
            </div>
          ) : null}
        </section>
      ) : null}

      {step === "mapping" && preview ? (
        <section aria-labelledby="import-mapping-title" className="df-ops-section">
          <h3 id="import-mapping-title" className="df-sales-section-title">
            Columns and fields
          </h3>
          <p className="df-field-helper">
            Columns are matched to contact fields by their header name. To change a match, rename the header in your file and upload it again.
          </p>
          {!hasRequiredMapping(preview) ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              A column named First name is required. Add it to the file and upload it again.
            </p>
          ) : null}
          <div className="df-ops-table-wrap">
            <table className="df-ops-table">
              <caption className="df-visually-hidden">Source columns and the contact field each one maps to</caption>
              <thead>
                <tr>
                  <th scope="col">Source column</th>
                  <th scope="col">Contact field</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {preview.columns.map((column) => {
                  const target = preview.suggested_target_fields.find((item) => item.value === column.suggested_field);
                  return (
                    <tr key={column.index}>
                      <td>{column.display_name}</td>
                      <td>{target?.label ?? "Not used"}</td>
                      <td>{target ? <Badge tone="success">Matched</Badge> : <Badge tone="neutral">Not imported</Badge>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="df-sales-muted">Supported contact fields: {preview.suggested_target_fields.map((item) => item.label).join(", ")}.</p>
        </section>
      ) : null}

      {step === "preview" && preview ? (
        <section aria-labelledby="import-preview-title" className="df-ops-section">
          <h3 id="import-preview-title" className="df-sales-section-title">
            Preview of the first rows
          </h3>
          <p className="df-field-helper">
            Showing {Math.min(PREVIEW_ROWS_SHOWN, preview.preview_rows.length)} of {preview.preview_rows.length} rows read.
            {preview.has_more_rows ? " The file has more rows; all of them are checked in validation." : ""}
          </p>
          <div className="df-ops-table-wrap">
            <table className="df-ops-table">
              <caption className="df-visually-hidden">Rows read from the file</caption>
              <thead>
                <tr>
                  {preview.columns.map((column) => (
                    <th key={column.index} scope="col">
                      {column.display_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.preview_rows.slice(0, PREVIEW_ROWS_SHOWN).map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {preview.columns.map((column) => (
                      <td key={column.index}>{row[column.display_name] ?? "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {step === "validate" ? (
        <section aria-labelledby="import-validate-title" className="df-ops-section">
          <h3 id="import-validate-title" className="df-sales-section-title">
            Validation
          </h3>
          <p className="df-field-helper">Validation checks every row and the duplicates against existing contacts and this file. It does not create anything.</p>
          {!validation ? (
            <p className="df-sales-muted">Run validation to see which rows are ready and which need changes.</p>
          ) : (
            <>
              <dl className="df-nested-summary">
                <div className="df-nested-summary-tile">
                  <dt>Rows read</dt>
                  <dd>{validation.total_rows}</dd>
                </div>
                <div className="df-nested-summary-tile">
                  <dt>Ready to import</dt>
                  <dd>{validation.valid_rows}</dd>
                </div>
                <div className={`df-nested-summary-tile${validation.invalid_rows > 0 ? " df-nested-summary-tile--attention" : ""}`}>
                  <dt>Need changes</dt>
                  <dd>{validation.invalid_rows}</dd>
                </div>
                <div className="df-nested-summary-tile">
                  <dt>Duplicates</dt>
                  <dd>
                    {grouped.duplicates.length}
                    {validation.errors_truncated ? "+" : ""}
                  </dd>
                </div>
              </dl>
              {validation.valid_rows === 0 ? (
                <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                  No row can be imported. Correct the file and upload it again.
                </p>
              ) : null}
              {validation.errors.length > 0 ? (
                <div className="df-ops-table-wrap">
                  <table className="df-ops-table">
                    <caption className="df-visually-hidden">Rows that need changes</caption>
                    <thead>
                      <tr>
                        <th scope="col">Row</th>
                        <th scope="col">Field</th>
                        <th scope="col">Issue</th>
                        <th scope="col">Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {validation.errors.map((item, index) => (
                        <ErrorRow key={`${item.row_number}-${item.field}-${index}`} item={item} />
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {validation.errors_truncated ? (
                <p className="df-field-helper">Only the first {validation.error_limit} issues are listed. Fix these and validate again to see the rest.</p>
              ) : null}
            </>
          )}
        </section>
      ) : null}

      {step === "confirm" && validation ? (
        <section aria-labelledby="import-confirm-title" className="df-ops-section">
          <h3 id="import-confirm-title" className="df-sales-section-title">
            Confirm the import
          </h3>
          <p>
            <strong>{validation.valid_rows}</strong> contact(s) will be created from <strong>{batch?.name}</strong>. <strong>{rowsNotImported(validation)}</strong>{" "}
            row(s) will not be imported.
          </p>
          <p className="df-field-helper">
            The import runs once. Rows that are duplicates are not created, and nothing is guessed or merged. Keep this window open while contacts are created.
          </p>
        </section>
      ) : null}

      {step === "processing" ? (
        <section aria-labelledby="import-processing-title" className="df-ops-section" aria-busy="true">
          <h3 id="import-processing-title" className="df-sales-section-title">
            Creating contacts
          </h3>
          <div className="df-ops-progress" role="progressbar" aria-label="Import in progress" aria-valuetext="Processing">
            <span className="df-ops-progress-bar" />
          </div>
          <p className="df-sales-muted" role="status">
            Creating contacts from {validation?.valid_rows ?? 0} valid row(s). This window updates when the report is ready.
          </p>
        </section>
      ) : null}

      {step === "report" ? (
        <section aria-labelledby="import-report-title" className="df-ops-section">
          <h3 id="import-report-title" className="df-sales-section-title">
            Import report
          </h3>
          {reportLoading ? (
            <p className="df-sales-muted" role="status">
              Loading the saved report…
            </p>
          ) : result || processed ? (
            <>
              <p>
                <Badge tone={importStatusTone((result ?? processed)?.status ?? "")}>{importStatusLabel((result ?? processed)?.status ?? "")}</Badge>
              </p>
              {reportCounts ? (
                <dl className="df-nested-summary">
                  <div className="df-nested-summary-tile">
                    <dt>Rows read</dt>
                    <dd>{reportCounts.total}</dd>
                  </div>
                  <div className="df-nested-summary-tile">
                    <dt>Contacts created</dt>
                    <dd>{(result ?? processed)?.contacts_created ?? reportCounts.successful}</dd>
                  </div>
                  <div className={`df-nested-summary-tile${reportCounts.failed > 0 ? " df-nested-summary-tile--attention" : ""}`}>
                    <dt>Not imported</dt>
                    <dd>{reportCounts.failed}</dd>
                  </div>
                  <div className="df-nested-summary-tile">
                    <dt>Skipped</dt>
                    <dd>{reportCounts.skipped}</dd>
                  </div>
                </dl>
              ) : null}
              {processingErrors.length > 0 ? (
                <>
                  <h4 className="df-sales-section-title">Rows not imported</h4>
                  <p className="df-field-helper">These rows were checked again while importing and could not be created.</p>
                  <div className="df-ops-table-wrap">
                    <table className="df-ops-table">
                      <caption className="df-visually-hidden">Rows not imported, with the reason</caption>
                      <thead>
                        <tr>
                          <th scope="col">Row</th>
                          <th scope="col">Field</th>
                          <th scope="col">Issue</th>
                          <th scope="col">Type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {processingErrors.map((item, index) => (
                          <ErrorRow key={`${item.row_number}-${item.field}-${index}`} item={item} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <p className="df-sales-muted">Every row that was read became a contact or was skipped as the report shows.</p>
              )}
              <p className="df-field-helper">
                {(result ?? processed)?.status === "pending"
                  ? "This file was read but not imported. Upload it again to start a new import."
                  : "This import has run. A file is imported once, so it cannot be run again."}
              </p>
            </>
          ) : (
            <p className="df-sales-muted">No saved report is available for this import.</p>
          )}
        </section>
      ) : null}

      {confirmDialog}
    </Dialog>
  );
}

function ErrorRow({ item }: { item: ImportValidationErrorDetail }) {
  const duplicate = item.code === "duplicate";
  return (
    <tr>
      <td>{item.row_number}</td>
      <td>{item.field}</td>
      <td>{item.message}</td>
      <td>
        <Badge tone={duplicate ? "pending" : "danger"}>{duplicate ? "Duplicate" : "Invalid value"}</Badge>
      </td>
    </tr>
  );
}
