import { useId, useRef, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";

import { Button, Dialog, SelectField, TextField, TextareaField } from "../../../components/ui";
import {
  DOCUMENT_ACCESS_CLASSIFICATIONS,
  DOCUMENT_CATEGORIES,
  documentApi,
  DOCUMENT_ALLOWED_EXTENSIONS,
  validateDocumentFile,
  type DocumentRecordType,
  type DocumentResponse,
} from "../../../services/documentApi";
import { ApiError } from "../../../lib/api";
import { DOCUMENT_TYPE_SUGGESTIONS, formatFileSize, LINKABLE_RECORD_TYPES, RECORD_TYPE_LABELS, UNSUPPORTED_LINK_NOTE, fileFormat } from "./document-workflow";
import type { RecordOptions } from "./document-lookups";

interface DocumentUploadDialogProps {
  recordOptions: RecordOptions;
  onClose: () => void;
  /** Called once the file is stored. `message` says whether the optional link also succeeded. */
  onUploaded: (message: string) => void;
}

interface UploadErrors {
  file?: string;
  documentType?: string;
  link?: string;
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "The document could not be uploaded. Please try again.";
}

/**
 * Uploads one document with its metadata and an optional link to one business record. The file is stored first. If the link then
 * fails, the document still exists, and the message says so and points to the detail view, rather than hiding the stored file.
 */
export function DocumentUploadDialog({ recordOptions, onClose, onUploaded }: DocumentUploadDialogProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("OTHER");
  const [documentType, setDocumentType] = useState("General document");
  const [access, setAccess] = useState("INTERNAL");
  const [linkType, setLinkType] = useState<DocumentRecordType | "">("");
  const [linkId, setLinkId] = useState("");
  const [errors, setErrors] = useState<UploadErrors>({});
  const [submitError, setSubmitError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const dirty = file !== null || displayName.trim() !== "" || description.trim() !== "" || linkType !== "";

  function chooseFile(next: File | undefined) {
    if (!next) return;
    const problem = validateDocumentFile(next);
    setErrors((current) => ({ ...current, file: problem ?? undefined }));
    if (problem) {
      setFile(null);
      return;
    }
    setFile(next);
    setDisplayName((current) => (current.trim() ? current : next.name));
  }

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    chooseFile(event.target.files?.[0]);
    if (inputRef.current) inputRef.current.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    chooseFile(event.dataTransfer.files?.[0]);
  }

  function changeCategory(next: string) {
    setCategory(next);
    const previousSuggestions = DOCUMENT_TYPE_SUGGESTIONS[category] ?? [];
    if (!documentType.trim() || previousSuggestions.includes(documentType)) {
      setDocumentType(DOCUMENT_TYPE_SUGGESTIONS[next]?.[0] ?? "General document");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;

    const found: UploadErrors = {};
    if (!file) found.file = "Choose a file to upload.";
    if (!documentType.trim()) found.documentType = "Enter the document type.";
    if (documentType.trim().length > 100) found.documentType = "Use 100 characters or fewer.";
    if (linkType && !linkId) found.link = "Choose the record to link, or leave the link empty.";
    setErrors(found);
    if (Object.keys(found).length > 0 || !file) return;

    inFlight.current = true;
    setBusy(true);
    setSubmitError("");
    let stored: DocumentResponse;
    try {
      stored = await documentApi.upload({
        file,
        displayName: displayName.trim() || file.name,
        description,
        category,
        documentType,
        accessClassification: access,
      });
    } catch (error) {
      setSubmitError(messageOf(error));
      inFlight.current = false;
      setBusy(false);
      return;
    }

    const name = stored.display_name;
    if (!linkType) {
      inFlight.current = false;
      onUploaded(`"${name}" was added to the document library.`);
      return;
    }

    try {
      await documentApi.updateAssociation(stored.id, { record_type: linkType, record_id: linkId });
      onUploaded(`"${name}" was added and linked to a ${RECORD_TYPE_LABELS[linkType].toLowerCase()}.`);
    } catch (error) {
      onUploaded(`"${name}" was added, but linking it failed: ${messageOf(error)} Open the document to link it again.`);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const suggestions = DOCUMENT_TYPE_SUGGESTIONS[category] ?? [];
  const listId = `${inputId}-types`;
  const recordChoices = linkType ? recordOptions[linkType] : [];

  return (
    <Dialog
      open
      onClose={onClose}
      title="Upload document"
      eyebrow="Document library"
      closeLabel="Close upload"
      size="md"
      busy={busy}
      dirty={dirty && !busy}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form="document-upload-form" variant="primary" loading={busy} disabled={busy}>
            Upload document
          </Button>
        </>
      }
    >
      <form id="document-upload-form" className="df-nested-form" onSubmit={(event) => void handleSubmit(event)} noValidate>
        {submitError ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {submitError}
          </p>
        ) : null}

        <div className="df-ops-field">
          <span className="df-field-label" id={`${inputId}-label`}>
            File <span aria-hidden="true">*</span>
          </span>
          <div
            className={`df-ops-dropzone${dragging ? " df-ops-dropzone--active" : ""}${errors.file ? " df-ops-dropzone--error" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <input
              ref={inputRef}
              id={inputId}
              type="file"
              className="df-visually-hidden"
              accept={DOCUMENT_ALLOWED_EXTENSIONS.join(",")}
              onChange={handleInput}
              disabled={busy}
              aria-labelledby={`${inputId}-label`}
              aria-describedby={`${inputId}-help`}
            />
            {file ? (
              <p className="df-ops-file">
                <strong>{file.name}</strong>
                <span className="df-sales-muted">
                  {fileFormat({ file_extension: null, original_filename: file.name })} · {formatFileSize(file.size)}
                </span>
              </p>
            ) : (
              <p className="df-sales-muted">Drop a file here, or choose one.</p>
            )}
            <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()} disabled={busy}>
              {file ? "Choose a different file" : "Choose file"}
            </Button>
          </div>
          <p id={`${inputId}-help`} className={errors.file ? "df-field-error" : "df-field-helper"} role={errors.file ? "alert" : undefined}>
            {errors.file ?? "PDF, PNG, JPG, TXT, CSV, DOCX or XLSX, up to 10 MB."}
          </p>
        </div>

        <TextField
          label="Display name"
          maxLength={255}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          helper="How the document appears in the library. Defaults to the file name."
          disabled={busy}
        />

        <SelectField
          label="Category"
          required
          value={category}
          options={DOCUMENT_CATEGORIES.map((item) => ({ value: item.value, label: item.label }))}
          onChange={(event) => changeCategory(event.target.value)}
          disabled={busy}
        />

        <TextField
          label="Document type"
          required
          maxLength={100}
          list={listId}
          value={documentType}
          onChange={(event) => setDocumentType(event.target.value)}
          helper={`Suggestions for this category: ${suggestions.join(", ")}.`}
          disabled={busy}
          error={errors.documentType}
        />
        <datalist id={listId}>
          {suggestions.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>

        <SelectField
          label="Access"
          value={access}
          options={DOCUMENT_ACCESS_CLASSIFICATIONS.map((item) => ({ value: item.value, label: item.label }))}
          onChange={(event) => setAccess(event.target.value)}
          disabled={busy}
          helper="Who may see this document. Restricted and confidential documents are shown to users with the right access."
        />

        <TextareaField
          label="Description"
          rows={3}
          maxLength={5000}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={busy}
        />

        <div className="df-nested-form-row">
          <SelectField
            label="Link to a record"
            value={linkType}
            options={[
              { value: "", label: "Not linked" },
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
            error={errors.link}
          />
        </div>
        <p className="df-field-helper">{UNSUPPORTED_LINK_NOTE}</p>
      </form>
    </Dialog>
  );
}
