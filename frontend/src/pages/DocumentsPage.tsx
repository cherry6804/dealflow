
import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useRef,
  useState,
} from "react";

import {
  DOCUMENT_ACCESS_CLASSIFICATIONS,
  DOCUMENT_CATEGORIES,
  documentApi,
  validateDocumentFile,
  type DocumentResponse,
} from "../services/documentApi";

import "./DocumentsPage.css";

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(value: string | null): string {
  if (!value) return "Just now";

  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Just now"
    : date.toLocaleString();
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(" ");
}

export default function DocumentsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("OTHER");
  const [documentType, setDocumentType] = useState("GENERAL");
  const [accessClassification, setAccessClassification] =
    useState("INTERNAL");

  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<DocumentResponse | null>(null);

  const [recentUploads, setRecentUploads] = useState<DocumentResponse[]>([]);

  function selectFile(selectedFile: File | undefined) {
    if (!selectedFile) return;

    setError(null);
    setSuccess(null);

    const validationError = validateDocumentFile(selectedFile);

    if (validationError) {
      setFile(null);
      setError(validationError);
      return;
    }

    setFile(selectedFile);
    setDisplayName((current) =>
      current.trim() ? current : selectedFile.name,
    );

    if (!fileInputRef.current) return;
    fileInputRef.current.value = "";
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0]);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files?.[0]);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (uploading) return;

    if (!file) {
      setError("Select a file before uploading.");
      return;
    }

    const validationError = validateDocumentFile(file);

    if (validationError) {
      setError(validationError);
      return;
    }

    if (!displayName.trim()) {
      setError("Enter a document name.");
      return;
    }

    if (!documentType.trim()) {
      setError("Enter a document type.");
      return;
    }

    setUploading(true);
    setError(null);
    setSuccess(null);

    try {
      const uploadedDocument = await documentApi.upload({
        file,
        displayName,
        description,
        category,
        documentType,
        accessClassification,
      });

      setSuccess(uploadedDocument);

      setRecentUploads((current) => [
        uploadedDocument,
        ...current.filter((item) => item.id !== uploadedDocument.id),
      ]);

      setFile(null);
      setDisplayName("");
      setDescription("");
      setCategory("OTHER");
      setDocumentType("GENERAL");
      setAccessClassification("INTERNAL");

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "The document could not be uploaded. Please try again.",
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="documents-page">
      <header className="documents-header">
        <div>
          <span className="documents-eyebrow">DOCUMENT MANAGEMENT</span>
          <h1>Documents</h1>
          <p className="documents-subtitle">
            Securely upload and classify your real estate business
            documents.
          </p>
        </div>

        <div className="documents-header-badge">
          <span aria-hidden="true">▤</span>
          <span>Organization workspace</span>
        </div>
      </header>

      <div className="documents-summary-grid">
        <article className="documents-summary-card">
          <span className="documents-summary-icon" aria-hidden="true">
            ↑
          </span>
          <div>
            <span className="documents-summary-label">Upload workflow</span>
            <strong>Ready to use</strong>
          </div>
        </article>

        <article className="documents-summary-card">
          <span className="documents-summary-icon" aria-hidden="true">
            ◈
          </span>
          <div>
            <span className="documents-summary-label">File size limit</span>
            <strong>10 MB per file</strong>
          </div>
        </article>

        <article className="documents-summary-card">
          <span className="documents-summary-icon" aria-hidden="true">
            ✓
          </span>
          <div>
            <span className="documents-summary-label">Access control</span>
            <strong>Organization-scoped</strong>
          </div>
        </article>
      </div>

      {error && (
        <div className="documents-alert documents-alert-error" role="alert">
          <span aria-hidden="true">!</span>
          <span>{error}</span>
          <button
            type="button"
            className="documents-alert-dismiss"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
          >
            ×
          </button>
        </div>
      )}

      {success && (
        <div className="documents-alert documents-alert-success" role="status">
          <span aria-hidden="true">✓</span>
          <div>
            <strong>Document uploaded successfully</strong>
            <p>{success.display_name}</p>
          </div>
          <button
            type="button"
            className="documents-alert-dismiss"
            aria-label="Dismiss success message"
            onClick={() => setSuccess(null)}
          >
            ×
          </button>
        </div>
      )}

      <div className="documents-layout">
        <section className="documents-panel">
          <div className="documents-panel-heading">
            <div>
              <h2>Upload a document</h2>
              <p>Add a file and organize it with useful metadata.</p>
            </div>
            <span className="documents-step-badge">NEW DOCUMENT</span>
          </div>

          <form onSubmit={handleSubmit}>
            <div
              className={`documents-dropzone ${dragging ? "is-dragging" : ""} ${file ? "has-file" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                  setDragging(false);
                }
              }}
              onDrop={handleDrop}
            >
              <input
                ref={fileInputRef}
                id="document-file-input"
                className="documents-visually-hidden"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.txt,.csv,.docx,.xlsx"
                onChange={handleFileChange}
                disabled={uploading}
              />

              <div className="documents-upload-symbol" aria-hidden="true">
                {file ? "▤" : "↑"}
              </div>

              {file ? (
                <>
                  <h3>{file.name}</h3>
                  <p>{formatFileSize(file.size)} · Ready to upload</p>
                  <button
                    type="button"
                    className="documents-text-button"
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Choose a different file
                  </button>
                </>
              ) : (
                <>
                  <h3>Drop your document here</h3>
                  <p>or select a file from your computer</p>
                  <button
                    type="button"
                    className="documents-secondary-button"
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Browse files
                  </button>
                  <span className="documents-file-hint">
                    PDF, PNG, JPG, TXT, CSV, DOCX or XLSX · Maximum 10 MB
                  </span>
                </>
              )}
            </div>

            <div className="documents-form-section">
              <div className="documents-form-section-heading">
                <span className="documents-form-number">01</span>
                <div>
                  <h3>Document details</h3>
                  <p>Identify the document for your team.</p>
                </div>
              </div>

              <div className="documents-form-grid">
                <label className="documents-field documents-field-full">
                  <span>Document name <span className="required">*</span></span>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    placeholder="e.g. Property Sale Agreement"
                    maxLength={255}
                    required
                    disabled={uploading}
                  />
                </label>

                <label className="documents-field">
                  <span>Category <span className="required">*</span></span>
                  <select
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                    required
                    disabled={uploading}
                  >
                    {DOCUMENT_CATEGORIES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="documents-field">
                  <span>Document type <span className="required">*</span></span>
                  <input
                    type="text"
                    value={documentType}
                    onChange={(event) => setDocumentType(event.target.value)}
                    placeholder="e.g. SALE_AGREEMENT"
                    maxLength={100}
                    required
                    disabled={uploading}
                  />
                  <small>Use a clear, consistent type identifier.</small>
                </label>

                <label className="documents-field documents-field-full">
                  <span>Description</span>
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Add optional context about this document..."
                    rows={3}
                    maxLength={2000}
                    disabled={uploading}
                  />
                </label>
              </div>
            </div>

            <div className="documents-form-section">
              <div className="documents-form-section-heading">
                <span className="documents-form-number">02</span>
                <div>
                  <h3>Access classification</h3>
                  <p>Choose the intended sensitivity level.</p>
                </div>
              </div>

              <label className="documents-field">
                <span>Classification <span className="required">*</span></span>
                <select
                  value={accessClassification}
                  onChange={(event) =>
                    setAccessClassification(event.target.value)
                  }
                  required
                  disabled={uploading}
                >
                  {DOCUMENT_ACCESS_CLASSIFICATIONS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <p className="documents-security-note">
                <span aria-hidden="true">ⓘ</span>
                <span>
                  Classification records the document&apos;s intended
                  sensitivity. It does not independently grant or revoke
                  access; server-side authorization remains authoritative.
                </span>
              </p>
            </div>

            <div className="documents-form-actions">
              <button
                type="button"
                className="documents-secondary-button"
                disabled={uploading}
                onClick={() => {
                  setFile(null);
                  setDisplayName("");
                  setDescription("");
                  setCategory("OTHER");
                  setDocumentType("GENERAL");
                  setAccessClassification("INTERNAL");
                  setError(null);
                  setSuccess(null);
                  if (fileInputRef.current) {
                    fileInputRef.current.value = "";
                  }
                }}
              >
                Clear form
              </button>

              <button
                type="submit"
                className="documents-primary-button"
                disabled={uploading || !file}
              >
                {uploading ? (
                  <>
                    <span className="documents-spinner" aria-hidden="true" />
                    Uploading…
                  </>
                ) : (
                  <>
                    <span aria-hidden="true">↑</span>
                    Upload document
                  </>
                )}
              </button>
            </div>
          </form>
        </section>

        <aside className="documents-side-column">
          <section className="documents-panel documents-guidance-panel">
            <span className="documents-guidance-icon" aria-hidden="true">
              ◈
            </span>
            <h2>Keep documents organized</h2>
            <p>
              Use consistent document types and categories so documents can
              be connected to the right business records in later workflow
              steps.
            </p>

            <ul className="documents-guidance-list">
              <li>
                <span>✓</span>
                Use descriptive document names
              </li>
              <li>
                <span>✓</span>
                Select the most relevant category
              </li>
              <li>
                <span>✓</span>
                Classify sensitive documents carefully
              </li>
            </ul>
          </section>

          <section className="documents-panel documents-recent-panel">
            <div className="documents-panel-heading">
              <div>
                <h2>Uploaded this session</h2>
                <p>Uploads completed in this page session.</p>
              </div>
              <span className="documents-count">{recentUploads.length}</span>
            </div>

            {recentUploads.length === 0 ? (
              <div className="documents-empty-state">
                <span aria-hidden="true">▤</span>
                <p>No uploads yet</p>
                <small>Your successful uploads will appear here.</small>
              </div>
            ) : (
              <ul className="documents-recent-list">
                {recentUploads.map((item) => (
                  <li key={item.id}>
                    <span className="documents-recent-file-icon" aria-hidden="true">
                      ▤
                    </span>
                    <div className="documents-recent-details">
                      <strong>{item.display_name}</strong>
                      <span>{formatLabel(item.category)}</span>
                      <small>{formatDate(item.uploaded_at ?? item.created_at)}</small>
                    </div>
                    <span
                      className="documents-status-indicator"
                      title={item.status}
                      aria-label={`Status: ${item.status}`}
                    />
                  </li>
                ))}
              </ul>
            )}

            <p className="documents-session-note">
              This list is session-only. A persistent document library and
              download workflow will be handled in subsequent stories.
            </p>
          </section>
        </aside>
      </div>

      <p className="documents-footer-note">
        <span aria-hidden="true">⌁</span>
        Files are uploaded to the currently selected organization through
        Dealsflo&apos;s authenticated API.
      </p>
    </section>
  );
}
