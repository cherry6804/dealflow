
import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ApiError } from "../lib/api";
import {
  importApi,
  type ImportPreview,
  type ImportValidationResult,
  type ImportResult,
} from "../services/importApi";
import "./ImportsPage.css";

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

type WorkflowStep = "upload" | "validation" | "result";

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatFieldName(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatStatus(value: string): string {
  return formatFieldName(value || "Unknown");
}

function getStepNumber(step: WorkflowStep): number {
  if (step === "upload") return 1;
  if (step === "validation") return 2;
  return 3;
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  return String(value);
}

export default function ImportsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [validation, setValidation] =
    useState<ImportValidationResult | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const [uploading, setUploading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [downloadingErrors, setDownloadingErrors] = useState(false);
  const [dragging, setDragging] = useState(false);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const busy = uploading || validating || processing;
  const activeStep: WorkflowStep = result
    ? "result"
    : validation
      ? "validation"
      : "upload";

  function validateFile(file: File): string | null {
    const extension = file.name.split(".").pop()?.toLowerCase();

    if (extension !== "csv" && extension !== "xlsx") {
      return "Choose a CSV or XLSX file.";
    }

    if (file.size === 0) {
      return "The selected file is empty.";
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      return "The file exceeds the 10 MB upload limit.";
    }

    return null;
  }

  function selectFile(file: File | null) {
    if (busy || result) {
      return;
    }

    setError("");
    setNotice("");
    setPreview(null);
    setValidation(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    const validationMessage = validateFile(file);

    if (validationMessage) {
      setSelectedFile(null);
      setError(validationMessage);
      return;
    }

    setSelectedFile(file);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0] ?? null);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);

    if (busy || result) {
      return;
    }

    selectFile(event.dataTransfer.files?.[0] ?? null);
  }

  async function handleUpload() {
    if (!selectedFile || busy || result) {
      return;
    }

    setUploading(true);
    setError("");
    setNotice("");
    setPreview(null);
    setValidation(null);

    try {
      const batch = await importApi.upload(selectedFile);
      const uploadedPreview = await importApi.preview(batch.id);

      setPreview(uploadedPreview);
      setNotice(
        "Preview ready. No contacts have been created. Review the file and validate its rows before importing.",
      );
    } catch (uploadError) {
      setError(getErrorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  }

  async function handleValidate() {
    if (!preview || busy || result) {
      return;
    }

    setValidating(true);
    setError("");
    setNotice("");
    setValidation(null);

    try {
      const validationResult = await importApi.validate(
        preview.import_batch_id,
      );

      setValidation(validationResult);

      if (validationResult.valid_rows > 0) {
        setNotice(
          "Validation completed. Review the row counts and errors before deciding whether to import.",
        );
      } else {
        setNotice(
          "Validation completed, but there are no valid rows to import. Review the validation errors.",
        );
      }
    } catch (validationError) {
      setError(getErrorMessage(validationError));
    } finally {
      setValidating(false);
    }
  }

  async function handleProcess() {
    if (!preview || !validation || busy || result) {
      return;
    }

    if (validation.valid_rows <= 0) {
      setError("There are no valid rows to import.");
      return;
    }

    const confirmed = window.confirm(
      `Import ${validation.valid_rows} valid row(s) from "${preview.source_filename}"? This will create contacts in the selected organization. This action may not be reversible.`,
    );

    if (!confirmed) {
      return;
    }

    setProcessing(true);
    setError("");
    setNotice("");

    try {
      await importApi.process(preview.import_batch_id);

      // Read the persisted result so the UI reflects the server's final state.
      const persistedResult = await importApi.result(
        preview.import_batch_id,
      );

      setResult(persistedResult);
      setNotice("Import processing finished. Review the result summary below.");
    } catch (processingError) {
      setError(getErrorMessage(processingError));
    } finally {
      setProcessing(false);
    }
  }

  async function handleRefreshResult() {
    if (!preview || busy) {
      return;
    }

    setError("");
    setNotice("");
    setDownloadingErrors(false);

    try {
      const persistedResult = await importApi.result(
        preview.import_batch_id,
      );
      setResult(persistedResult);
      setNotice("The saved import result has been refreshed.");
    } catch (refreshError) {
      setError(getErrorMessage(refreshError));
    }
  }

  async function handleDownloadErrors() {
    if (!preview || downloadingErrors) {
      return;
    }

    setDownloadingErrors(true);
    setError("");

    try {
      await importApi.downloadErrors(preview.import_batch_id);
      setNotice("The error CSV download has been requested.");
    } catch (downloadError) {
      setError(getErrorMessage(downloadError));
    } finally {
      setDownloadingErrors(false);
    }
  }

  function resetImport() {
    if (busy || downloadingErrors) {
      return;
    }

    setSelectedFile(null);
    setPreview(null);
    setValidation(null);
    setResult(null);
    setError("");
    setNotice("");

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  const validationErrors = validation?.errors ?? [];
  const resultErrors = result?.errors ?? [];
  const hasProcessingErrors =
    Boolean(result) &&
    ((result?.failed_rows ?? 0) > 0 || resultErrors.length > 0);

  return (
    <section className="imports-page">
      <header className="imports-header">
        <div>
          <span className="imports-eyebrow">DATA MANAGEMENT</span>
          <h1>Import contacts</h1>
          <p className="imports-subtitle">
            Upload a CSV or Excel file, review its contents, validate the
            rows, and explicitly confirm before creating contacts.
          </p>
        </div>

        {(preview || selectedFile) && (
          <button
            className="imports-secondary-button"
            type="button"
            onClick={resetImport}
            disabled={busy || downloadingErrors}
          >
            Start new import
          </button>
        )}
      </header>

      <nav
        className="imports-step-indicator"
        aria-label="Import workflow progress"
      >
        <div
          className={`imports-step ${
            activeStep === "upload" ? "is-current" : ""
          } ${getStepNumber(activeStep) > 1 ? "is-complete" : ""}`}
        >
          <span>{activeStep === "upload" ? "1" : "✓"}</span>
          <div>
            <strong>Upload & preview</strong>
            <small>Review file columns</small>
          </div>
        </div>

        <div className="imports-step-connector" />

        <div
          className={`imports-step ${
            activeStep === "validation" ? "is-current" : ""
          } ${activeStep === "result" ? "is-complete" : ""}`}
        >
          <span>
            {activeStep === "validation"
              ? "2"
              : activeStep === "result"
                ? "✓"
                : "2"}
          </span>
          <div>
            <strong>Validate rows</strong>
            <small>Review data issues</small>
          </div>
        </div>

        <div className="imports-step-connector" />

        <div
          className={`imports-step ${
            activeStep === "result" ? "is-current" : ""
          }`}
        >
          <span>3</span>
          <div>
            <strong>Import contacts</strong>
            <small>Confirm and view results</small>
          </div>
        </div>
      </nav>

      {error && (
        <div className="imports-alert imports-alert-error" role="alert">
          <div>
            <strong>Something needs your attention</strong>
            <p>{error}</p>
          </div>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError("")}
          >
            ×
          </button>
        </div>
      )}

      {notice && (
        <div className="imports-alert imports-alert-success" role="status">
          <div>
            <strong>Import workflow update</strong>
            <p>{notice}</p>
          </div>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            ×
          </button>
        </div>
      )}

      {!preview && (
        <section className="imports-panel">
          <div className="imports-panel-heading">
            <div>
              <h2>Upload your file</h2>
              <p>
                Start with a CSV or XLSX file containing the contact data you
                want to import.
              </p>
            </div>
            <span className="imports-file-limit">Maximum 10 MB</span>
          </div>

          <div
            className={`imports-dropzone ${
              dragging ? "is-dragging" : ""
            }`}
            onDragOver={(event) => {
              event.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <div className="imports-upload-icon" aria-hidden="true">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 16V4" />
                <path d="m7 9 5-5 5 5" />
                <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
              </svg>
            </div>
            <h3>
              {dragging ? "Drop your file here" : "Choose a file to get started"}
            </h3>
            <p>Drag and drop your file here, or browse from your computer.</p>

            <input
              ref={fileInputRef}
              className="imports-visually-hidden"
              id="imports-file-input"
              type="file"
              accept=".csv,.xlsx"
              onChange={handleFileChange}
              disabled={busy}
            />

            <button
              className="imports-secondary-button"
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
            >
              Browse files
            </button>
          </div>

          {selectedFile && (
            <div className="imports-selected-file">
              <div className="imports-file-icon">
                {selectedFile.name.toLowerCase().endsWith(".csv")
                  ? "CSV"
                  : "XLSX"}
              </div>
              <div className="imports-file-details">
                <strong>{selectedFile.name}</strong>
                <span>{formatFileSize(selectedFile.size)}</span>
              </div>
              <button
                className="imports-text-button"
                type="button"
                onClick={() => selectFile(null)}
                disabled={busy}
              >
                Remove
              </button>
            </div>
          )}

          <div className="imports-upload-actions">
            <p>Uploading and previewing do not create contacts.</p>
            <button
              className="imports-primary-button"
              type="button"
              onClick={handleUpload}
              disabled={!selectedFile || busy}
            >
              {uploading ? "Uploading and previewing…" : "Upload & preview"}
            </button>
          </div>
        </section>
      )}

      {preview && (
        <>
          <section className="imports-panel">
            <div className="imports-panel-heading">
              <div>
                <h2>File preview</h2>
                <p>
                  Review the detected columns and sample rows before running
                  validation.
                </p>
              </div>
              <span className="imports-count">
                {preview.columns.length} columns
              </span>
            </div>

            <div className="imports-selected-file">
              <div className="imports-file-icon">
                {preview.source_format.toUpperCase()}
              </div>
              <div className="imports-file-details">
                <strong>{preview.source_filename}</strong>
                <span>
                  {preview.worksheet_name
                    ? `Worksheet: ${preview.worksheet_name}`
                    : "File preview"}
                </span>
              </div>
              <span className="imports-detection-status is-detected">
                Preview ready
              </span>
            </div>

            <div className="imports-table-wrap">
              <table className="imports-table">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Detected header</th>
                    <th>Suggested field</th>
                    <th>Detection</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.columns.map((column) => (
                    <tr key={`${column.index}-${column.source_name}`}>
                      <td>{column.index + 1}</td>
                      <td>
                        <div className="imports-column-name">
                          <span className="imports-column-index">
                            {column.index + 1}
                          </span>
                          <strong>
                            {column.source_name || "Unnamed column"}
                          </strong>
                        </div>
                      </td>
                      <td>
                        {column.suggested_field ? (
                          <span className="imports-suggestion">
                            {formatFieldName(column.suggested_field)}
                          </span>
                        ) : (
                          <span className="imports-unmapped">
                            No suggestion
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className={`imports-detection-status ${
                            column.suggested_field
                              ? "is-detected"
                              : "is-unmapped"
                          }`}
                        >
                          {column.suggested_field
                            ? "Suggested"
                            : "Review"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="imports-helper-note">
              Suggested fields are informational. They do not represent a
              saved or editable column mapping.
            </p>
          </section>

          <section className="imports-panel">
            <div className="imports-panel-heading">
              <div>
                <h2>Sample rows</h2>
                <p>
                  Check that the file content looks correct. This is a
                  non-mutating preview.
                </p>
              </div>
              <span className="imports-count">
                {preview.preview_rows.length} shown
              </span>
            </div>

            {preview.preview_rows.length > 0 && preview.columns.length > 0 ? (
              <div className="imports-table-wrap">
                <table className="imports-table imports-sample-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      {preview.columns.map((column) => (
                        <th key={`${column.index}-${column.source_name}`}>
                          {column.source_name || `Column ${column.index + 1}`}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        <td className="imports-row-number">{rowIndex + 1}</td>
                        {preview.columns.map((column) => {
                          const value = row[column.source_name];

                          return (
                            <td
                              key={`${rowIndex}-${column.index}`}
                              className={
                                value === null || value === undefined || value === ""
                                  ? "imports-empty-cell"
                                  : undefined
                              }
                            >
                              {formatCellValue(value)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="imports-empty-preview">
                <h3>No sample rows to display</h3>
                <p>
                  The preview did not return sample data. You can still run
                  validation to see whether the file can be imported.
                </p>
              </div>
            )}

            <div className="imports-preview-footer">
              <span>
                Preview limit: <strong>{preview.preview_row_limit}</strong> rows
              </span>
              <span>
                {preview.has_more_rows
                  ? "Additional rows are not shown in this preview."
                  : "All available preview rows are shown."}
              </span>
            </div>

            {!validation && (
              <div className="imports-upload-actions">
                <p>Validation checks rows without creating contacts.</p>
                <button
                  className="imports-primary-button"
                  type="button"
                  onClick={handleValidate}
                  disabled={busy}
                >
                  {validating ? "Validating rows…" : "Validate rows"}
                </button>
              </div>
            )}
          </section>
        </>
      )}

      {validation && (
        <section className="imports-panel">
          <div className="imports-panel-heading">
            <div>
              <h2>Validation summary</h2>
              <p>
                Review the server-reported validation results before
                confirming the import.
              </p>
            </div>
            <span className="imports-detection-status is-detected">
              {formatStatus(validation.status)}
            </span>
          </div>

          <div className="imports-metrics">
            <div className="imports-metric">
              <span>Total rows</span>
              <strong>{validation.total_rows}</strong>
            </div>
            <div className="imports-metric is-positive">
              <span>Valid rows</span>
              <strong>{validation.valid_rows}</strong>
            </div>
            <div className="imports-metric is-negative">
              <span>Invalid rows</span>
              <strong>{validation.invalid_rows}</strong>
            </div>
            <div className="imports-metric">
              <span>Skipped rows</span>
              <strong>{validation.skipped_rows}</strong>
            </div>
          </div>

          {validationErrors.length > 0 ? (
            <>
              <div className="imports-panel-heading imports-subsection-heading">
                <div>
                  <h3>Validation errors</h3>
                  <p>
                    Correct the source data and upload a revised file if
                    required.
                  </p>
                </div>
                <span className="imports-count">
                  {validationErrors.length} shown
                </span>
              </div>

              <div className="imports-table-wrap">
                <table className="imports-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Field</th>
                      <th>Error code</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validationErrors.map((item, index) => (
                      <tr
                        key={`${item.row_number}-${item.field}-${item.code}-${index}`}
                      >
                        <td>{item.row_number}</td>
                        <td>{item.field || "—"}</td>
                        <td>
                          <code>{item.code}</code>
                        </td>
                        <td>{item.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {validation.errors_truncated && (
                <p className="imports-helper-note">
                  The server limited the number of validation errors returned.
                  Some errors may not be displayed here.
                </p>
              )}
            </>
          ) : (
            <p className="imports-helper-note">
              No validation errors were returned by the server.
            </p>
          )}

          <div className="imports-confirmation">
            <strong>Import confirmation</strong>
            <p>
              Validation has not created any contacts. Continuing will ask for
              confirmation before the server processes the valid rows.
            </p>

            {validation.valid_rows <= 0 && (
              <p className="imports-confirmation-warning">
                There are no valid rows to import. Review the validation
                errors and upload a corrected file.
              </p>
            )}
          </div>

          <div className="imports-upload-actions">
            <button
              className="imports-secondary-button"
              type="button"
              onClick={handleValidate}
              disabled={busy}
            >
              {validating ? "Revalidating…" : "Run validation again"}
            </button>
            <button
              className="imports-primary-button"
              type="button"
              onClick={handleProcess}
              disabled={busy || validation.valid_rows <= 0}
            >
              {processing
                ? "Processing import…"
                : `Confirm & import ${validation.valid_rows} valid row(s)`}
            </button>
          </div>
        </section>
      )}

      {result && (
        <section className="imports-panel">
          <div className="imports-panel-heading">
            <div>
              <h2>Import result</h2>
              <p>
                These counts come from the persisted server result for this
                import batch.
              </p>
            </div>
            <span
              className={`imports-detection-status ${
                result.failed_rows > 0 ? "is-unmapped" : "is-detected"
              }`}
            >
              {formatStatus(result.status)}
            </span>
          </div>

          <div className="imports-metrics">
            <div className="imports-metric">
              <span>Total rows</span>
              <strong>{result.total_rows}</strong>
            </div>
            <div className="imports-metric">
              <span>Processed</span>
              <strong>{result.processed_rows}</strong>
            </div>
            <div className="imports-metric is-positive">
              <span>Successful rows</span>
              <strong>{result.successful_rows}</strong>
            </div>
            <div className="imports-metric is-negative">
              <span>Failed rows</span>
              <strong>{result.failed_rows}</strong>
            </div>
            <div className="imports-metric">
              <span>Skipped rows</span>
              <strong>{result.skipped_rows}</strong>
            </div>
            <div className="imports-metric">
              <span>Contacts created</span>
              <strong>{result.contacts_created}</strong>
            </div>
          </div>

          {resultErrors.length > 0 && (
            <>
              <div className="imports-panel-heading imports-subsection-heading">
                <div>
                  <h3>Processing errors</h3>
                  <p>
                    Review the row-level details returned by the server.
                  </p>
                </div>
                <span className="imports-count">
                  {resultErrors.length} shown
                </span>
              </div>

              <div className="imports-table-wrap">
                <table className="imports-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Field</th>
                      <th>Error code</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultErrors.map((item, index) => (
                      <tr
                        key={`${item.row_number}-${item.field}-${item.code}-${index}`}
                      >
                        <td>{item.row_number}</td>
                        <td>{item.field || "—"}</td>
                        <td>
                          <code>{item.code}</code>
                        </td>
                        <td>{item.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {result.errors_truncated && (
                <p className="imports-helper-note">
                  The server limited the number of processing errors returned.
                  The downloadable error file may provide additional details.
                </p>
              )}
            </>
          )}

          {hasProcessingErrors && (
            <div className="imports-upload-actions">
              <p>Download the processing error report for further review.</p>
              <button
                className="imports-secondary-button"
                type="button"
                onClick={handleDownloadErrors}
                disabled={downloadingErrors}
              >
                {downloadingErrors
                  ? "Preparing download…"
                  : "Download errors CSV"}
              </button>
            </div>
          )}

          <div className="imports-upload-actions">
            <p>
              If you need to check the saved server result again, refresh it
              below.
            </p>
            <button
              className="imports-secondary-button"
              type="button"
              onClick={handleRefreshResult}
              disabled={busy}
            >
              Refresh saved result
            </button>
          </div>
        </section>
      )}
    </section>
  );
}
