import { useEffect, useState, type FormEvent } from "react";

import { RecordDialog, RecordProperty } from "../../../components/record/RecordDialog";
import { Button, SelectField, useConfirmation } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { documentApi, type DocumentRecordType, type DocumentResponse } from "../../../services/documentApi";
import { formatDateTime } from "../../sales/sales-shared";
import type { RecordOptions } from "./document-lookups";
import {
  accessLabel,
  categoryLabel,
  fileFormat,
  formatFileSize,
  LINKABLE_RECORD_TYPES,
  previewKind,
  RECORD_TYPE_LABELS,
  UNSUPPORTED_LINK_NOTE,
  type LinkedRecord,
  type PreviewKind,
} from "./document-workflow";

interface DocumentDetailDialogProps {
  document: DocumentResponse;
  link: LinkedRecord | null;
  uploaderName: string;
  recordOptions: RecordOptions;
  onClose: () => void;
  /** Called after a change. The message describes what changed; the file itself is never removed here. */
  onChanged: (message: string) => void;
}

const TEXT_PREVIEW_LIMIT = 20_000;

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; kind: Exclude<PreviewKind, "none">; url: string | null; text: string | null }
  | { status: "error"; message: string };

/** Loads the file for preview only when the format can show in the page. Object URLs are revoked when the dialog closes. */
function usePreview(document: DocumentResponse, kind: PreviewKind): PreviewState {
  const [state, setState] = useState<PreviewState>({ status: kind === "none" ? "idle" : "loading" });

  useEffect(() => {
    if (kind === "none") return;
    let cancelled = false;
    let objectUrl: string | null = null;

    documentApi
      .fetchFile(document.id)
      .then(async (blob) => {
        if (cancelled) return;
        if (kind === "text") {
          const text = (await blob.text()).slice(0, TEXT_PREVIEW_LIMIT);
          if (!cancelled) setState({ status: "ready", kind, url: null, text });
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setState({ status: "ready", kind, url: objectUrl, text: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", message: messageOf(error) });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.id, kind]);

  return state;
}

/**
 * Document details. The file preview loads only for formats the browser can show. Changing or removing the link to a record never
 * deletes the file, and the copy says so. Name, category and type are set at upload, so they are shown read-only.
 */
export function DocumentDetailDialog({ document, link, uploaderName, recordOptions, onClose, onChanged }: DocumentDetailDialogProps) {
  const kind = previewKind(document);
  const preview = usePreview(document, kind);
  const [confirm, confirmDialog] = useConfirmation();
  const [editingLink, setEditingLink] = useState(false);
  const [linkType, setLinkType] = useState<DocumentRecordType | "">(link?.type ?? "");
  const [linkId, setLinkId] = useState(link?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloadError, setDownloadError] = useState("");

  async function handleDownload() {
    if (busy) return;
    setBusy(true);
    setDownloadError("");
    try {
      await documentApi.download(document.id, document.original_filename);
    } catch (downloadFailure) {
      setDownloadError(messageOf(downloadFailure));
    } finally {
      setBusy(false);
    }
  }

  async function saveLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!linkType || !linkId) {
      setError("Choose a record type and a record.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await documentApi.updateAssociation(document.id, { record_type: linkType, record_id: linkId });
      setEditingLink(false);
      onChanged(`Linked to a ${RECORD_TYPE_LABELS[linkType].toLowerCase()}. The file is unchanged.`);
    } catch (saveError) {
      setError(messageOf(saveError));
    } finally {
      setBusy(false);
    }
  }

  async function removeLink() {
    if (busy || !link) return;
    const confirmed = await confirm(
      `The document will no longer be linked to this ${RECORD_TYPE_LABELS[link.type].toLowerCase()}. The file stays in the library and can be linked again later.`,
      { title: "Remove link?", confirmLabel: "Remove link", tone: "danger" },
    );
    if (!confirmed) return;
    setBusy(true);
    setError("");
    try {
      await documentApi.updateAssociation(document.id, { record_type: null, record_id: null });
      onChanged("The link was removed. The file is still in the library.");
    } catch (removeError) {
      setError(messageOf(removeError));
    } finally {
      setBusy(false);
    }
  }

  const recordChoices = linkType ? recordOptions[linkType] : [];

  const main = (
    <div className="df-ops-detail">
      <section className="df-ops-section" aria-labelledby="document-preview-title">
        <h3 id="document-preview-title" className="df-sales-section-title">
          Preview
        </h3>
        {kind === "none" ? (
          <p className="df-sales-muted">Preview is not available for {fileFormat(document)} files. Download the file to open it.</p>
        ) : preview.status === "loading" ? (
          <p className="df-sales-muted" role="status">
            Loading preview…
          </p>
        ) : preview.status === "error" ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            The preview could not be loaded. {preview.message}
          </p>
        ) : preview.status === "ready" && preview.kind === "image" && preview.url ? (
          <img className="df-ops-preview-image" src={preview.url} alt={`Preview of ${document.display_name}`} />
        ) : preview.status === "ready" && preview.kind === "pdf" && preview.url ? (
          <iframe className="df-ops-preview-frame" src={preview.url} title={`Preview of ${document.display_name}`} />
        ) : preview.status === "ready" && preview.kind === "text" ? (
          <pre className="df-ops-preview-text" tabIndex={0} aria-label={`Text preview of ${document.display_name}`}>
            {preview.text}
          </pre>
        ) : null}
        <p className="df-field-helper">Each preview is recorded as a document access in the audit trail.</p>
      </section>

      {document.description ? (
        <section className="df-ops-section" aria-label="Description">
          <h3 className="df-sales-section-title">Description</h3>
          <p className="df-ops-prewrap">{document.description}</p>
        </section>
      ) : null}

      <section className="df-ops-section" aria-labelledby="document-link-title">
        <h3 id="document-link-title" className="df-sales-section-title">
          Linked record
        </h3>
        {link && !editingLink ? (
          <div className="df-ops-link-row">
            <p>
              <span className="df-sales-muted">{RECORD_TYPE_LABELS[link.type]}</span> <strong>{link.label}</strong>
            </p>
            <div className="df-sales-form-actions">
              <Button variant="secondary" size="sm" onClick={() => setEditingLink(true)} disabled={busy}>
                Change link
              </Button>
              <Button variant="tertiary" size="sm" onClick={() => void removeLink()} disabled={busy}>
                Remove link
              </Button>
            </div>
          </div>
        ) : editingLink || !link ? (
          <form className="df-nested-form" onSubmit={(event) => void saveLink(event)} noValidate>
            <div className="df-nested-form-row">
              <SelectField
                label="Record type"
                value={linkType}
                options={[
                  { value: "", label: "Choose a type" },
                  ...LINKABLE_RECORD_TYPES.map((type) => ({ value: type, label: RECORD_TYPE_LABELS[type] })),
                ]}
                onChange={(event) => {
                  setLinkType(event.target.value as DocumentRecordType | "");
                  setLinkId("");
                }}
                disabled={busy}
              />
              <SelectField
                label="Record"
                value={linkId}
                options={[{ value: "", label: linkType ? "Choose a record" : "Choose a type first" }, ...recordChoices]}
                onChange={(event) => setLinkId(event.target.value)}
                disabled={busy || !linkType}
              />
            </div>
            <div className="df-sales-form-actions">
              {editingLink ? (
                <Button variant="secondary" size="sm" onClick={() => setEditingLink(false)} disabled={busy}>
                  Cancel
                </Button>
              ) : null}
              <Button type="submit" variant="primary" size="sm" loading={busy} disabled={busy}>
                Save link
              </Button>
            </div>
          </form>
        ) : null}
        <p className="df-field-helper">{UNSUPPORTED_LINK_NOTE}</p>
        {error ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {error}
          </p>
        ) : null}
      </section>
      {confirmDialog}
    </div>
  );

  const aside = (
    <>
      <dl className="df-sales-properties">
        <RecordProperty label="Category">{categoryLabel(document.category)}</RecordProperty>
        <RecordProperty label="Document type">{document.document_type}</RecordProperty>
        <RecordProperty label="Format">{fileFormat(document)}</RecordProperty>
        <RecordProperty label="Size">{formatFileSize(document.file_size_bytes)}</RecordProperty>
        <RecordProperty label="Access">{accessLabel(document.access_classification)}</RecordProperty>
        <RecordProperty label="Status">Available</RecordProperty>
        <RecordProperty label="Uploaded by">{uploaderName}</RecordProperty>
        <RecordProperty label="Uploaded">{formatDateTime(document.uploaded_at ?? document.created_at)}</RecordProperty>
        <RecordProperty label="Last modified">{formatDateTime(document.updated_at)}</RecordProperty>
        <RecordProperty label="File name">
          <span className="df-ops-prewrap">{document.original_filename}</span>
        </RecordProperty>
      </dl>
      <p className="df-field-helper">
        Name, category and document type are set at upload. Editing them after upload is not available yet. Deleting a file is not available
        here either: removing a link keeps the file.
      </p>
    </>
  );

  return (
    <RecordDialog
      open
      onClose={onClose}
      eyebrow={categoryLabel(document.category)}
      title={document.display_name}
      closeLabel="Close document details"
      busy={busy}
      main={main}
      aside={aside}
      footer={
        <>
          {downloadError ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {downloadError}
            </p>
          ) : null}
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <Button variant="primary" onClick={() => void handleDownload()} loading={busy} disabled={busy}>
            Download
          </Button>
        </>
      }
    />
  );
}
