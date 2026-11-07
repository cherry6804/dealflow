import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../../components/grid/gridLayout";
import type { GridFilterField } from "../../../components/grid/gridFilters";
import { Badge, Button } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { DOCUMENT_CATEGORIES, documentApi, type DocumentResponse } from "../../../services/documentApi";
import { fetchAllPages, formatShortDate } from "../../sales/sales-shared";
import "../../sales/sales.css";
import "./documents.css";
import { DocumentDetailDialog } from "./DocumentDetailDialog";
import { DocumentUploadDialog } from "./DocumentUploadDialog";
import { EMPTY_DOCUMENT_LOOKUPS, loadDocumentLookups, type DocumentLookups } from "./document-lookups";
import {
  accessLabel,
  categoryCounts,
  categoryLabel,
  filterDocuments,
  fileFormat,
  formatFileSize,
  linkedRecord,
  uploaderName,
  type LinkedRecord,
} from "./document-workflow";

const COLUMNS: GridColumnDef[] = [
  { key: "name", label: "Document", defaultWidth: 300, primary: true },
  { key: "category", label: "Category", defaultWidth: 170 },
  { key: "linked", label: "Linked record", defaultWidth: 220 },
  { key: "format", label: "Format", defaultWidth: 90 },
  { key: "size", label: "Size", defaultWidth: 100 },
  { key: "status", label: "Status", defaultWidth: 120 },
  { key: "uploader", label: "Uploaded by", defaultWidth: 170 },
  { key: "uploaded", label: "Uploaded", defaultWidth: 130 },
  { key: "modified", label: "Last modified", defaultWidth: 140 },
  { key: "type", label: "Document type", defaultWidth: 170, defaultVisible: false },
  { key: "access", label: "Access", defaultWidth: 130, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  {
    key: "link",
    label: "Linked",
    type: "select",
    options: [
      { value: "linked", label: "Linked to a record" },
      { value: "unlinked", label: "Not linked" },
    ],
  },
  {
    key: "access",
    label: "Access",
    type: "select",
    options: [
      { value: "PUBLIC", label: "Public" },
      { value: "INTERNAL", label: "Internal" },
      { value: "CONFIDENTIAL", label: "Confidential" },
      { value: "RESTRICTED", label: "Restricted" },
    ],
  },
];

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Check your connection and try again.";
}

async function loadDocuments(): Promise<DocumentResponse[]> {
  return fetchAllPages((page) => documentApi.list({ page, pageSize: 100 }));
}

/**
 * Document library for real-estate records. Documents load in full, so search, category counts and sorting cover every file. Category
 * chips and the grid filters narrow the list. Opening a row shows its details, preview, download and record link.
 */
export default function DocumentsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [lookups, setLookups] = useState<DocumentLookups>(EMPTY_DOCUMENT_LOOKUPS);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [items, lookupData] = await Promise.all([loadDocuments(), loadDocumentLookups().catch(() => EMPTY_DOCUMENT_LOOKUPS)]);
      setDocuments(items);
      setLookups(lookupData);
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
    Promise.all([loadDocuments(), loadDocumentLookups().catch(() => EMPTY_DOCUMENT_LOOKUPS)])
      .then(([items, lookupData]) => {
        if (cancelled) return;
        setDocuments(items);
        setLookups(lookupData);
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

  const linkOf = useCallback((document: DocumentResponse): LinkedRecord | null => linkedRecord(document, lookups.links), [lookups.links]);
  const counts = useMemo(() => categoryCounts(documents), [documents]);
  const rows = useMemo(() => filterDocuments(documents, { search, category, link: null }, linkOf), [documents, search, category, linkOf]);
  const selected = selectedId ? (documents.find((document) => document.id === selectedId) ?? null) : null;

  const sortValue = useCallback(
    (document: DocumentResponse, key: string): string | number | null => {
      switch (key) {
        case "category":
          return categoryLabel(document.category);
        case "linked":
          return linkOf(document)?.label ?? null;
        case "format":
          return fileFormat(document);
        case "size":
          return document.file_size_bytes;
        case "status":
          return document.status;
        case "uploader":
          return uploaderName(document.uploaded_by_user_id, lookups.uploaders);
        case "uploaded":
          return new Date(document.uploaded_at ?? document.created_at).getTime();
        case "modified":
          return new Date(document.updated_at).getTime();
        case "type":
          return document.document_type;
        case "access":
          return accessLabel(document.access_classification);
        default:
          return document.display_name;
      }
    },
    [linkOf, lookups.uploaders],
  );

  const renderCell = useCallback(
    (document: DocumentResponse, key: string) => {
      switch (key) {
        case "category":
          return categoryLabel(document.category);
        case "linked": {
          const link = linkOf(document);
          return link ? (
            <span className="df-sales-stack">
              <span className="df-sales-muted">{link.type === "lead" ? "Lead" : link.type === "property" ? "Property" : "Deal"}</span>
              <span>{link.label}</span>
            </span>
          ) : (
            <span className="df-sales-muted">Not linked</span>
          );
        }
        case "format":
          return fileFormat(document);
        case "size":
          return formatFileSize(document.file_size_bytes);
        case "status":
          return <Badge tone="success">Available</Badge>;
        case "uploader":
          return uploaderName(document.uploaded_by_user_id, lookups.uploaders);
        case "uploaded":
          return formatShortDate(document.uploaded_at ?? document.created_at);
        case "modified":
          return formatShortDate(document.updated_at);
        case "type":
          return document.document_type;
        case "access":
          return accessLabel(document.access_classification);
        default:
          return (
            <span className="df-sales-stack">
              <strong className="df-sales-primary">{document.display_name}</strong>
              <span className="df-sales-muted">{document.original_filename}</span>
            </span>
          );
      }
    },
    [linkOf, lookups.uploaders],
  );

  const filterValue = useCallback(
    (document: DocumentResponse, key: string): string | null => {
      switch (key) {
        case "link":
          return linkOf(document) ? "linked" : "unlinked";
        case "access":
          return document.access_classification;
        default:
          return null;
      }
    },
    [linkOf],
  );

  return (
    <div className="df-sales-page df-ops-page">
      <h1 className="df-visually-hidden">Documents</h1>

      <section className="df-ops-intro" aria-label="Document library summary">
        <div>
          <p className="df-ops-eyebrow">Operations</p>
          <h2 className="df-ops-title">Document library</h2>
          <p className="df-sales-muted">Contracts, title records, identity proofs and other files, kept against the properties, leads and deals they belong to.</p>
        </div>
        <Button variant="primary" onClick={() => setUploadOpen(true)}>
          Upload document
        </Button>
      </section>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <div className="df-ops-chips" role="group" aria-label="Filter by category">
        <button
          type="button"
          className={`df-ops-chip${category === null ? " df-ops-chip--active" : ""}`}
          aria-pressed={category === null}
          onClick={() => setCategory(null)}
        >
          All documents <span className="df-ops-chip-count">{documents.length}</span>
        </button>
        {DOCUMENT_CATEGORIES.map((item) => {
          const count = counts.get(item.value) ?? 0;
          const active = category === item.value;
          return (
            <button
              key={item.value}
              type="button"
              className={`df-ops-chip${active ? " df-ops-chip--active" : ""}`}
              aria-pressed={active}
              onClick={() => setCategory(active ? null : item.value)}
              title={item.label}
            >
              {item.label} <span className="df-ops-chip-count">{count}</span>
            </button>
          );
        })}
      </div>

      <EnterpriseDataGrid<DocumentResponse>
        gridId="documents"
        ariaLabel="Documents"
        columns={COLUMNS}
        rows={rows}
        rowKey={(document) => document.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search documents"
        searchPlaceholder="Search name, type, file, record or category"
        emptyTitle="No documents yet"
        emptyMessage="Upload a contract, title record, identity proof or other business document to start the library."
        noMatchTitle="No documents match this search or filter"
        noMatchMessage="Try another search, choose another category, or clear the filters."
        createLabel="Upload document"
        onCreate={() => setUploadOpen(true)}
        onOpenRow={(document) => setSelectedId(document.id)}
        onRefresh={() => {
          setStatus("loading");
          void reload();
        }}
        totalCount={documents.length}
        rangeLabel={search || category ? "Filtered" : "All documents shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {selected ? (
        <DocumentDetailDialog
          key={selected.id}
          document={selected}
          link={linkOf(selected)}
          uploaderName={uploaderName(selected.uploaded_by_user_id, lookups.uploaders)}
          recordOptions={lookups.options}
          onClose={() => setSelectedId(null)}
          onChanged={(message) => {
            setNotice(message);
            void reload();
          }}
        />
      ) : null}

      {uploadOpen ? (
        <DocumentUploadDialog
          recordOptions={lookups.options}
          onClose={() => setUploadOpen(false)}
          onUploaded={(message) => {
            setUploadOpen(false);
            setNotice(message);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}
