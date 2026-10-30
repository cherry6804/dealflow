
import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  DOCUMENT_ACCESS_CLASSIFICATIONS,
  DOCUMENT_CATEGORIES,
  documentApi,
  validateDocumentFile,
  type DocumentResponse,
  type DocumentRecordType,
} from "../services/documentApi";

import { leadsApi, type Lead } from "../services/leadApi";
import { contactsApi, type Contact } from "../services/contactApi";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import {
  propertiesApi,
  type Property,
} from "../services/propertyApi";
import { dealsApi, type Deal } from "../services/dealApi";

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
    .map(
      (word) =>
        word.charAt(0) + word.slice(1).toLowerCase(),
    )
    .join(" ");
}

function getPropertyLabel(property: Property): string {
  const location = [
    property.address_line_1,
    property.locality,
    property.city,
  ]
    .filter(Boolean)
    .join(", ");

  return location || "Property address unavailable";
}

function getContactName(contact: Contact | null | undefined): string {
  if (!contact) return "Contact details unavailable";

  const name = [contact.first_name, contact.last_name]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(" ")
    .trim();

  return name || contact.email || contact.phone || "Unnamed contact";
}

function getCustomerProfileName(
  profile: CustomerProfile | undefined,
): string {
  if (!profile) return "Customer details unavailable";

  const contact = profile.contact;
  const name = [contact?.first_name, contact?.last_name]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(" ")
    .trim();

  return name || contact?.email || contact?.phone || "Unnamed customer";
}

function getDealLabel(
  deal: Deal,
  customerProfiles: CustomerProfile[],
  properties: Property[],
): string {
  const customer = customerProfiles.find(
    (profile) => profile.id === deal.customer_profile_id,
  );
  const property = properties.find(
    (item) => item.id === deal.property_id,
  );

  return [
    getCustomerProfileName(customer),
    property ? getPropertyLabel(property) : "Property details unavailable",
    formatLabel(deal.stage),
  ].join(" · ");
}

function getLeadLabel(lead: Lead, contacts: Contact[]): string {
  const contact = contacts.find((item) => item.id === lead.contact_id);
  return `${getContactName(contact)} · ${formatLabel(lead.status)}`;
}

export default function DocumentsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Upload form
  const [file, setFile] = useState<File | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("OTHER");
  const [documentType, setDocumentType] = useState("GENERAL");
  const [accessClassification, setAccessClassification] =
    useState("INTERNAL");

  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [downloadingDocumentId, setDownloadingDocumentId] =
    useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] =
    useState<DocumentResponse | null>(null);

  // Document library
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [refreshingDocuments, setRefreshingDocuments] =
    useState(false);
  const [documentsError, setDocumentsError] =
    useState<string | null>(null);
  const [documentPage, setDocumentPage] = useState(1);
  const [documentTotal, setDocumentTotal] = useState(0);
  const [documentTotalPages, setDocumentTotalPages] = useState(0);

  // Available business records
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [customerProfiles, setCustomerProfiles] = useState<CustomerProfile[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] =
    useState<string | null>(null);

  // Document association editor
  const [editingDocumentId, setEditingDocumentId] =
    useState<string | null>(null);
  const [recordType, setRecordType] =
    useState<DocumentRecordType | "">("");
  const [recordId, setRecordId] = useState("");
  const [savingAssociation, setSavingAssociation] =
    useState(false);
  const [associationError, setAssociationError] =
    useState<string | null>(null);
  const [associationMessage, setAssociationMessage] =
    useState<string | null>(null);

  const loadDocuments = useCallback(async (page = 1) => {
    setDocumentsError(null);

    try {
      const response = await documentApi.list({
        page,
        pageSize: 20,
      });

      setDocuments(response.items);
      setDocumentPage(response.page);
      setDocumentTotal(response.total);
      setDocumentTotalPages(response.total_pages);
    } catch (loadError) {
      setDocumentsError(
        loadError instanceof Error
          ? loadError.message
          : "Documents could not be loaded. Please try again.",
      );
    } finally {
      setLoadingDocuments(false);
      setRefreshingDocuments(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // Load record options for association management.
  useEffect(() => {
    let cancelled = false;

    async function loadRecords() {
      setRecordsLoading(true);
      setRecordsError(null);

      try {
        const [
          leadResponse,
          propertyResponse,
          dealResponse,
          contactResponse,
          customerProfileResponse,
        ] = await Promise.all([
          leadsApi.list({ page: 1, page_size: 100 }),
          propertiesApi.search({ page: 1, page_size: 100 }),
          dealsApi.list({ page: 1, page_size: 100 }),
          contactsApi.list({ page: 1, page_size: 100 }),
          customerProfilesApi.list({ page: 1, page_size: 100 }),
        ]);

        if (cancelled) return;

        setLeads(leadResponse.items);
        setProperties(propertyResponse.items);
        setDeals(dealResponse.items);
        setContacts(contactResponse.items);
        setCustomerProfiles(customerProfileResponse.items);
      } catch (loadError) {
        if (cancelled) return;

        setRecordsError(
          loadError instanceof Error
            ? loadError.message
            : "Business records could not be loaded.",
        );
      } finally {
        if (!cancelled) {
          setRecordsLoading(false);
        }
      }
    }

    void loadRecords();

    return () => {
      cancelled = true;
    };
  }, []);

  function handleRefreshDocuments() {
    setRefreshingDocuments(true);
    void loadDocuments(documentPage);
  }

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

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0]);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files?.[0]);
  }

  async function handleDownload(document: DocumentResponse) {
    if (downloadingDocumentId) return;

    setDownloadingDocumentId(document.id);
    setError(null);

    try {
      await documentApi.download(
        document.id,
        document.original_filename,
      );
    } catch (downloadError) {
      setError(
        downloadError instanceof Error
          ? downloadError.message
          : "The document could not be downloaded. Please try again.",
      );
    } finally {
      setDownloadingDocumentId(null);
    }
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
      await loadDocuments(1);

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

  function startAssociationEdit(document: DocumentResponse) {
    setEditingDocumentId(document.id);
    setAssociationError(null);
    setAssociationMessage(null);

    if (document.lead_id) {
      setRecordType("lead");
      setRecordId(document.lead_id);
    } else if (document.property_id) {
      setRecordType("property");
      setRecordId(document.property_id);
    } else if (document.deal_id) {
      setRecordType("deal");
      setRecordId(document.deal_id);
    } else {
      setRecordType("");
      setRecordId("");
    }
  }

  function cancelAssociationEdit() {
    setEditingDocumentId(null);
    setRecordType("");
    setRecordId("");
    setAssociationError(null);
  }

  function getAssociationLabel(document: DocumentResponse): string {
    if (document.lead_id) {
      const lead = leads.find(
        (item) => item.id === document.lead_id,
      );

      return lead
        ? `Lead · ${getLeadLabel(lead, contacts)}`
        : "Lead · Details unavailable";
    }

    if (document.property_id) {
      const property = properties.find(
        (item) => item.id === document.property_id,
      );

      return property
        ? `Property · ${getPropertyLabel(property)}`
        : "Property · Address unavailable";
    }

    if (document.deal_id) {
      const deal = deals.find(
        (item) => item.id === document.deal_id,
      );

      return deal
        ? `Deal · ${getDealLabel(deal, customerProfiles, properties)}`
        : "Deal · Details unavailable";
    }

    return "Not linked";
  }

  async function saveAssociation(document: DocumentResponse) {
    if (savingAssociation) return;

    if (recordType && !recordId) {
      setAssociationError("Select a record before saving.");
      return;
    }

    setSavingAssociation(true);
    setAssociationError(null);
    setAssociationMessage(null);

    try {
      const updatedDocument =
        await documentApi.updateAssociation(document.id, {
          record_type: recordType || null,
          record_id: recordType ? recordId : null,
        });

      setDocuments((current) =>
        current.map((item) =>
          item.id === updatedDocument.id
            ? updatedDocument
            : item,
        ),
      );

      setAssociationMessage(
        recordType
          ? `Link saved for "${updatedDocument.display_name}".`
          : `Document "${updatedDocument.display_name}" was unlinked.`,
      );

      setEditingDocumentId(null);
      setRecordType("");
      setRecordId("");
    } catch (saveError) {
      setAssociationError(
        saveError instanceof Error
          ? saveError.message
          : "The document association could not be saved.",
      );
    } finally {
      setSavingAssociation(false);
    }
  }

  function renderRecordOptions() {
    if (recordType === "lead") {
      return leads.map((lead) => (
        <option key={lead.id} value={lead.id}>
          {getLeadLabel(lead, contacts)}
        </option>
      ));
    }

    if (recordType === "property") {
      return properties.map((property) => (
        <option key={property.id} value={property.id}>
          {getPropertyLabel(property)}
        </option>
      ));
    }

    if (recordType === "deal") {
      return deals.map((deal) => (
        <option key={deal.id} value={deal.id}>
          {getDealLabel(deal, customerProfiles, properties)}
        </option>
      ));
    }

    return null;
  }

  return (
    <section className="documents-page">
      <header className="documents-header">
        <div>
          <span className="documents-eyebrow">
            DOCUMENT MANAGEMENT
          </span>
          <h1>Documents</h1>
          <p className="documents-subtitle">
            Securely upload, classify, and link documents to your
            real estate business records.
          </p>
        </div>

        <div className="documents-header-badge">
          <span aria-hidden="true">▤</span>
          <span>Organization workspace</span>
        </div>
      </header>

      <div className="documents-summary-grid">
        <article className="documents-summary-card">
          <span
            className="documents-summary-icon"
            aria-hidden="true"
          >
            ↑
          </span>
          <div>
            <span className="documents-summary-label">
              Upload workflow
            </span>
            <strong>Ready to use</strong>
          </div>
        </article>

        <article className="documents-summary-card">
          <span
            className="documents-summary-icon"
            aria-hidden="true"
          >
            ◈
          </span>
          <div>
            <span className="documents-summary-label">
              File size limit
            </span>
            <strong>10 MB per file</strong>
          </div>
        </article>

        <article className="documents-summary-card">
          <span
            className="documents-summary-icon"
            aria-hidden="true"
          >
            ✓
          </span>
          <div>
            <span className="documents-summary-label">
              Record associations
            </span>
            <strong>Leads · Properties · Deals</strong>
          </div>
        </article>
      </div>

      {error && (
        <div
          className="documents-alert documents-alert-error"
          role="alert"
        >
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
        <div
          className="documents-alert documents-alert-success"
          role="status"
        >
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

      {associationMessage && (
        <div
          className="documents-alert documents-alert-success"
          role="status"
        >
          <span aria-hidden="true">✓</span>
          <span>{associationMessage}</span>
          <button
            type="button"
            className="documents-alert-dismiss"
            aria-label="Dismiss association message"
            onClick={() => setAssociationMessage(null)}
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
              <p>
                Add a file and organize it with useful metadata.
              </p>
            </div>
            <span className="documents-step-badge">
              NEW DOCUMENT
            </span>
          </div>

          <form onSubmit={handleSubmit}>
            <div
              className={`documents-dropzone ${
                dragging ? "is-dragging" : ""
              } ${file ? "has-file" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (
                  !event.currentTarget.contains(
                    event.relatedTarget as Node,
                  )
                ) {
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

              <div
                className="documents-upload-symbol"
                aria-hidden="true"
              >
                {file ? "▤" : "↑"}
              </div>

              {file ? (
                <>
                  <h3>{file.name}</h3>
                  <p>
                    {formatFileSize(file.size)} · Ready to upload
                  </p>
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
                    PDF, PNG, JPG, TXT, CSV, DOCX or XLSX ·
                    Maximum 10 MB
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
                  <span>
                    Document name <span className="required">*</span>
                  </span>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(event) =>
                      setDisplayName(event.target.value)
                    }
                    placeholder="e.g. Property Sale Agreement"
                    maxLength={255}
                    required
                    disabled={uploading}
                  />
                </label>

                <label className="documents-field">
                  <span>
                    Category <span className="required">*</span>
                  </span>
                  <select
                    value={category}
                    onChange={(event) =>
                      setCategory(event.target.value)
                    }
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
                  <span>
                    Document type <span className="required">*</span>
                  </span>
                  <input
                    type="text"
                    value={documentType}
                    onChange={(event) =>
                      setDocumentType(event.target.value)
                    }
                    placeholder="e.g. SALE_AGREEMENT"
                    maxLength={100}
                    required
                    disabled={uploading}
                  />
                  <small>
                    Use a clear, consistent type identifier.
                  </small>
                </label>

                <label className="documents-field documents-field-full">
                  <span>Description</span>
                  <textarea
                    value={description}
                    onChange={(event) =>
                      setDescription(event.target.value)
                    }
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
                <span>
                  Classification <span className="required">*</span>
                </span>
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
                  sensitivity. It does not independently grant or
                  revoke access; server-side authorization remains
                  authoritative.
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
                    <span
                      className="documents-spinner"
                      aria-hidden="true"
                    />
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
            <span
              className="documents-guidance-icon"
              aria-hidden="true"
            >
              ◈
            </span>
            <h2>Keep documents organized</h2>
            <p>
              Link documents to the business records they belong to.
              You can change or remove a link at any time without
              deleting the document.
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
                Link files to leads, properties, or deals
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
                <h2>Document library</h2>
                <p>Saved documents in your organization.</p>
              </div>

              <div className="documents-recent-actions">
                <span className="documents-count">
                  {documentTotal}
                </span>
                <button
                  type="button"
                  className="documents-text-button"
                  onClick={handleRefreshDocuments}
                  disabled={
                    refreshingDocuments || loadingDocuments
                  }
                >
                  {refreshingDocuments ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            </div>

            {documentsError && (
              <div
                className="documents-alert documents-alert-error"
                role="alert"
              >
                <span>{documentsError}</span>
                <button
                  type="button"
                  className="documents-text-button"
                  onClick={handleRefreshDocuments}
                  disabled={refreshingDocuments}
                >
                  Retry
                </button>
              </div>
            )}

            {loadingDocuments ? (
              <div
                className="documents-empty-state"
                role="status"
              >
                <p>Loading documents…</p>
              </div>
            ) : documents.length === 0 && !documentsError ? (
              <div className="documents-empty-state">
                <span aria-hidden="true">▤</span>
                <p>No documents found</p>
                <small>
                  Upload a document to start building your library.
                </small>
              </div>
            ) : documents.length > 0 ? (
              <ul className="documents-recent-list">
                {documents.map((item) => (
                  <li key={item.id}>
                    <span
                      className="documents-recent-file-icon"
                      aria-hidden="true"
                    >
                      ▤
                    </span>

                    <div className="documents-recent-details">
                      <strong>{item.display_name}</strong>
                      <span>{formatLabel(item.category)}</span>
                      <small>
                        {formatFileSize(item.file_size_bytes ?? 0)}
                        {" · "}
                        {formatDate(
                          item.uploaded_at ?? item.created_at,
                        )}
                      </small>
                      <small>{formatLabel(item.status)}</small>

                      <small className="documents-association-label">
                        {getAssociationLabel(item)}
                      </small>

                      {item.status === "AVAILABLE" && (
                        <button
                          type="button"
                          className="documents-text-button"
                          onClick={() =>
                            startAssociationEdit(item)
                          }
                          disabled={savingAssociation}
                        >
                          {editingDocumentId === item.id
                            ? "Editing link…"
                            : item.lead_id ||
                                item.property_id ||
                                item.deal_id
                              ? "Change link"
                              : "Link to a record"}
                        </button>
                      )}

                      {editingDocumentId === item.id && (
                        <div className="documents-association-editor">
                          <label className="documents-field">
                            <span>Record type</span>
                            <select
                              value={recordType}
                              onChange={(event) => {
                                setRecordType(
                                  event.target.value as
                                    | DocumentRecordType
                                    | "",
                                );
                                setRecordId("");
                                setAssociationError(null);
                              }}
                              disabled={
                                savingAssociation ||
                                recordsLoading
                              }
                            >
                              <option value="">Not linked</option>
                              <option value="lead">Lead</option>
                              <option value="property">
                                Property
                              </option>
                              <option value="deal">Deal</option>
                            </select>
                          </label>

                          {recordType && (
                            <label className="documents-field">
                              <span>Business record</span>
                              <select
                                value={recordId}
                                onChange={(event) =>
                                  setRecordId(event.target.value)
                                }
                                disabled={
                                  savingAssociation ||
                                  recordsLoading ||
                                  Boolean(recordsError)
                                }
                              >
                                <option value="">
                                  Select a record
                                </option>
                                {renderRecordOptions()}
                              </select>
                            </label>
                          )}

                          {recordsLoading && (
                            <small role="status">
                              Loading business records…
                            </small>
                          )}

                          {recordsError && (
                            <small role="alert">
                              {recordsError}
                            </small>
                          )}

                          {associationError && (
                            <small role="alert">
                              {associationError}
                            </small>
                          )}

                          <div className="documents-form-actions">
                            <button
                              type="button"
                              className="documents-secondary-button"
                              onClick={cancelAssociationEdit}
                              disabled={savingAssociation}
                            >
                              Cancel
                            </button>

                            <button
                              type="button"
                              className="documents-primary-button"
                              onClick={() =>
                                void saveAssociation(item)
                              }
                              disabled={
                                savingAssociation ||
                                recordsLoading ||
                                Boolean(recordsError) ||
                                (Boolean(recordType) && !recordId)
                              }
                            >
                              {savingAssociation
                                ? "Saving…"
                                : recordType
                                  ? "Save link"
                                  : "Unlink document"}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="documents-recent-actions">
                      <span
                        className="documents-status-indicator"
                        title={item.status}
                        aria-label={`Status: ${item.status}`}
                      />

                      <button
                        type="button"
                        className="documents-text-button"
                        onClick={() => void handleDownload(item)}
                        disabled={
                          downloadingDocumentId !== null ||
                          item.status !== "AVAILABLE"
                        }
                        aria-label={`Download ${item.display_name}`}
                      >
                        {downloadingDocumentId === item.id
                          ? "Downloading…"
                          : "Download"}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}

            {!loadingDocuments && documentTotalPages > 1 && (
              <div className="documents-form-actions">
                <button
                  type="button"
                  className="documents-secondary-button"
                  disabled={
                    documentPage <= 1 || refreshingDocuments
                  }
                  onClick={() => {
                    setLoadingDocuments(true);
                    void loadDocuments(documentPage - 1);
                  }}
                >
                  Previous
                </button>

                <span>
                  Page {documentPage} of {documentTotalPages}
                </span>

                <button
                  type="button"
                  className="documents-secondary-button"
                  disabled={
                    documentPage >= documentTotalPages ||
                    refreshingDocuments
                  }
                  onClick={() => {
                    setLoadingDocuments(true);
                    void loadDocuments(documentPage + 1);
                  }}
                >
                  Next
                </button>
              </div>
            )}

            <p className="documents-session-note">
              Documents are loaded from the server and remain
              available after refreshing the page. Downloads and
              record associations are checked by the server against
              your organization and permissions.
            </p>
          </section>
        </aside>
      </div>

      <p className="documents-footer-note">
        <span aria-hidden="true">⌁</span>
        Files are uploaded to the currently selected organization
        through Dealsflo&apos;s authenticated API.
      </p>
    </section>
  );
}
