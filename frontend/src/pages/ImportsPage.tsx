import { useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { ApiError } from "../lib/api";
import {
  importApi,
  type ImportPreview,
} from "../services/importApi";

import "./ImportsPage.css";

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;

  if (error instanceof Error) return error.message;

  return "Something went wrong. Please try again.";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatFieldName(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export default function ImportsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function validateFile(file: File): string | null {
    const extension = file.name.split(".").pop()?.toLowerCase();

    if (!extension || !["csv", "xlsx"].includes(extension)) {
      return "Choose a CSV or XLSX file.";
    }

    if (file.size === 0) {
      return "The selected file is empty.";
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      return "The file must be 10 MB or smaller.";
    }

    return null;
  }

  function selectFile(file: File | null) {
    setError("");
    setNotice("");
    setPreview(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    const validationError = validateFile(file);

    if (validationError) {
      setSelectedFile(null);
      setError(validationError);
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
    selectFile(event.dataTransfer.files[0] ?? null);
  }

  async function handleUpload() {
    if (!selectedFile || uploading) return;

    setUploading(true);
    setError("");
    setNotice("");
    setPreview(null);

    try {
      const batch = await importApi.upload(selectedFile);
      const result = await importApi.preview(batch.id);

      setPreview(result);
      setNotice(
        "Preview ready. No contacts were created or activated.",
      );
    } catch (uploadError) {
      setError(getErrorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  }

  function resetImport() {
    if (uploading) return;

    setSelectedFile(null);
    setPreview(null);
    setError("");
    setNotice("");
  }

  return (
    <section className="imports-page">
      <header className="imports-header">
        <div>
          <span className="imports-eyebrow">DATA MANAGEMENT</span>
          <h1>Import contacts</h1>
          <p className="imports-subtitle">
            Bring your existing contact data into DealFlow and review
            how columns are detected before moving to the next step.
          </p>
        </div>
      </header>

      <section className="imports-step-indicator" aria-label="Import steps">
        <div className="imports-step is-current">
          <span>1</span>
          <div>
            <strong>Upload and preview</strong>
            <small>Choose a CSV or Excel file</small>
          </div>
        </div>
        <span className="imports-step-connector" aria-hidden="true" />
        <div className="imports-step">
          <span>2</span>
          <div>
            <strong>Validate rows</strong>
            <small>Review data issues</small>
          </div>
        </div>
        <span className="imports-step-connector" aria-hidden="true" />
        <div className="imports-step">
          <span>3</span>
          <div>
            <strong>Import contacts</strong>
            <small>Confirm the final import</small>
          </div>
        </div>
      </section>

      {error && (
        <div className="imports-alert imports-alert-error" role="alert">
          <div>
            <strong>Unable to prepare preview</strong>
            <p>{error}</p>
          </div>
          <button
            type="button"
            onClick={() => setError("")}
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      {notice && (
        <div className="imports-alert imports-alert-success" role="status">
          <div>
            <strong>Preview ready</strong>
            <p>{notice}</p>
          </div>
          <button
            type="button"
            onClick={() => setNotice("")}
            aria-label="Dismiss notice"
          >
            ×
          </button>
        </div>
      )}

      <section className="imports-panel">
        <header className="imports-panel-heading">
          <div>
            <h2>Upload your file</h2>
            <p>
              Start with a spreadsheet containing your existing contact
              details.
            </p>
          </div>
          <span className="imports-file-limit">CSV or XLSX · Max 10 MB</span>
        </header>

        <div
          className={`imports-dropzone ${dragging ? "is-dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node)) {
              setDragging(false);
            }
          }}
          onDrop={handleDrop}
        >
          <div className="imports-upload-icon" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 16V4" />
              <path d="m7 9 5-5 5 5" />
              <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
            </svg>
          </div>

          <h3>Choose a file to get started</h3>
          <p>Drag and drop your file here, or browse your computer.</p>

          <button
            type="button"
            className="imports-secondary-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            Browse files
          </button>

          <input
            ref={fileInputRef}
            className="imports-visually-hidden"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={handleFileChange}
            disabled={uploading}
            aria-label="Choose a CSV or XLSX file"
          />
        </div>

        {selectedFile && (
          <div className="imports-selected-file">
            <div className="imports-file-icon" aria-hidden="true">
              {selectedFile.name.toLowerCase().endsWith(".csv")
                ? "CSV"
                : "XLSX"}
            </div>
            <div className="imports-file-details">
              <strong>{selectedFile.name}</strong>
              <span>{formatFileSize(selectedFile.size)}</span>
            </div>
            <button
              type="button"
              className="imports-text-button"
              onClick={resetImport}
              disabled={uploading}
            >
              Remove
            </button>
          </div>
        )}

        <div className="imports-upload-actions">
          <p>
            <span aria-hidden="true">ⓘ</span> Previewing a file does not
            create or activate contacts.
          </p>
          <button
            type="button"
            className="imports-primary-button"
            onClick={() => void handleUpload()}
            disabled={!selectedFile || uploading}
          >
            {uploading ? "Preparing preview…" : "Upload and preview"}
          </button>
        </div>
      </section>

      {preview && (
        <>
          <section className="imports-panel">
            <header className="imports-panel-heading">
              <div>
                <h2>Detected columns</h2>
                <p>
                  Review the detected column names and the suggested contact
                  fields.
                </p>
              </div>
              <span className="imports-count">
                {preview.columns.length} columns
              </span>
            </header>

            <div className="imports-table-wrap">
              <table className="imports-table">
                <thead>
                  <tr>
                    <th scope="col">Source column</th>
                    <th scope="col">Suggested contact field</th>
                    <th scope="col">Detection</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.columns.map((column) => (
                    <tr key={`${column.index}-${column.display_name}`}>
                      <td>
                        <div className="imports-column-name">
                          <span className="imports-column-index">
                            {column.index + 1}
                          </span>
                          <strong>{column.display_name}</strong>
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
                          {column.suggested_field ? "Suggested" : "Review"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="imports-helper-note">
              Suggestions are based on column headings. They are not saved
              mappings, and they do not validate the data in each row.
            </p>
          </section>

          <section className="imports-panel">
            <header className="imports-panel-heading">
              <div>
                <h2>Sample data</h2>
                <p>
                  {preview.worksheet_name
                    ? `First worksheet: ${preview.worksheet_name}. `
                    : ""}
                  Showing up to {preview.preview_row_limit} sample rows.
                </p>
              </div>
              <span className="imports-count">
                {preview.preview_rows.length} rows shown
              </span>
            </header>

            {preview.preview_rows.length === 0 ? (
              <div className="imports-empty-preview">
                <h3>No sample data rows found</h3>
                <p>
                  The file contains a header row, but no sample rows were
                  available to display.
                </p>
              </div>
            ) : (
              <div className="imports-table-wrap">
                <table className="imports-table imports-sample-table">
                  <thead>
                    <tr>
                      <th scope="col">Row</th>
                      {preview.columns.map((column) => (
                        <th
                          scope="col"
                          key={`${column.index}-${column.display_name}`}
                        >
                          {column.display_name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        <td className="imports-row-number">{rowIndex + 1}</td>
                        {preview.columns.map((column) => (
                          <td
                            key={`${rowIndex}-${column.index}`}
                            title={
                              row[column.display_name] ?? "Empty cell"
                            }
                          >
                            {row[column.display_name] ?? (
                              <span className="imports-empty-cell">—</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <footer className="imports-preview-footer">
              <span>
                {preview.has_more_rows
                  ? `This is a sample only. The file may contain more rows than shown.`
                  : "End of available sample rows."}
              </span>
              <span>
                Contacts created: <strong>{preview.contacts_created}</strong>
              </span>
            </footer>
          </section>
        </>
      )}
    </section>
  );
}