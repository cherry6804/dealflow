import { DOCUMENT_CATEGORIES, type DocumentRecordType, type DocumentResponse } from "../../../services/documentApi";

/**
 * Document rules for the workspace. Categories, record links and file types are the ones the document API accepts. Nothing here
 * invents a capability: record types the API cannot link (requirements, site visits, contacts) are described as unsupported.
 */

export const CATEGORY_HINTS: Readonly<Record<string, string>> = {
  IDENTITY_KYC: "Identity proofs and know-your-customer records.",
  OWNERSHIP_TITLE: "Title deeds and proof of ownership.",
  LEGAL_COMPLIANCE: "Legal opinions, approvals and compliance records.",
  PROPERTY_RECORD: "Property papers such as plans, approvals and records.",
  MARKETING: "Brochures, listings and marketing material.",
  AGREEMENT: "Sale, lease and other signed agreements and contracts.",
  FINANCIAL: "Payment receipts, invoices and financial records.",
  CUSTOMER: "Documents supplied by or about a customer.",
  DEAL: "Documents for a deal or transaction.",
  OTHER: "Anything that does not fit another category.",
};

/** Suggested document types per category. They are prompts for the user, not a fixed list the API enforces. */
export const DOCUMENT_TYPE_SUGGESTIONS: Readonly<Record<string, readonly string[]>> = {
  IDENTITY_KYC: ["Passport", "PAN card", "Aadhaar card", "Driving licence"],
  OWNERSHIP_TITLE: ["Sale deed", "Title deed", "Encumbrance certificate", "Property tax receipt"],
  LEGAL_COMPLIANCE: ["Legal opinion", "Approval letter", "NOC", "Compliance certificate"],
  PROPERTY_RECORD: ["Floor plan", "Site plan", "Approved layout", "Property photos"],
  MARKETING: ["Brochure", "Listing sheet", "Price sheet"],
  AGREEMENT: ["Sale agreement", "Lease agreement", "Booking form", "Memorandum of understanding"],
  FINANCIAL: ["Payment receipt", "Invoice", "Bank statement", "Commission statement"],
  CUSTOMER: ["Customer letter", "Requirement form", "Correspondence"],
  DEAL: ["Offer letter", "Negotiation note", "Deal summary"],
  OTHER: ["General document"],
};

export const RECORD_TYPE_LABELS: Readonly<Record<DocumentRecordType, string>> = {
  lead: "Lead",
  property: "Property",
  deal: "Deal",
};

/** Record types the document API can link. Anything else is shown as unsupported, never as a control. */
export const LINKABLE_RECORD_TYPES: readonly DocumentRecordType[] = ["lead", "property", "deal"];

export const UNSUPPORTED_LINK_NOTE =
  "Documents can be linked to a lead, property or deal. Linking to requirements, site visits or contacts is not supported yet.";

export function categoryLabel(value: string): string {
  return DOCUMENT_CATEGORIES.find((item) => item.value === value)?.label ?? value;
}

export function accessLabel(value: string): string {
  switch (value) {
    case "PUBLIC":
      return "Public";
    case "INTERNAL":
      return "Internal";
    case "CONFIDENTIAL":
      return "Confidential";
    case "RESTRICTED":
      return "Restricted";
    default:
      return value;
  }
}

export function fileFormat(document: Pick<DocumentResponse, "file_extension" | "original_filename">): string {
  const extension = document.file_extension ?? document.original_filename.slice(document.original_filename.lastIndexOf("."));
  return extension.replace(/^\./, "").toUpperCase() || "FILE";
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export type PreviewKind = "pdf" | "image" | "text" | "none";

/** Formats the browser can show in the page without a plug-in. Other formats are download only. */
export function previewKind(document: Pick<DocumentResponse, "file_extension" | "original_filename">): PreviewKind {
  const extension = fileFormat(document).toLowerCase();
  if (extension === "pdf") return "pdf";
  if (["png", "jpg", "jpeg"].includes(extension)) return "image";
  if (["txt", "csv"].includes(extension)) return "text";
  return "none";
}

export interface LinkedRecord {
  type: DocumentRecordType;
  id: string;
  label: string;
}

export interface LinkLookup {
  leads: ReadonlyMap<string, string>;
  properties: ReadonlyMap<string, string>;
  deals: ReadonlyMap<string, string>;
}

export function linkedRecord(document: DocumentResponse, lookup: LinkLookup): LinkedRecord | null {
  if (document.lead_id) {
    return { type: "lead", id: document.lead_id, label: lookup.leads.get(document.lead_id) ?? "Lead unavailable" };
  }
  if (document.property_id) {
    return { type: "property", id: document.property_id, label: lookup.properties.get(document.property_id) ?? "Property unavailable" };
  }
  if (document.deal_id) {
    return { type: "deal", id: document.deal_id, label: lookup.deals.get(document.deal_id) ?? "Deal unavailable" };
  }
  return null;
}

export interface DocumentFilters {
  search: string;
  category: string | null;
  /** "linked", "unlinked", or null for both. */
  link: "linked" | "unlinked" | null;
}

export function filterDocuments(
  documents: readonly DocumentResponse[],
  filters: DocumentFilters,
  linkOf: (document: DocumentResponse) => LinkedRecord | null,
): DocumentResponse[] {
  const needle = filters.search.trim().toLowerCase();
  return documents.filter((document) => {
    if (filters.category && document.category !== filters.category) return false;
    if (filters.link === "linked" && !linkOf(document)) return false;
    if (filters.link === "unlinked" && linkOf(document)) return false;
    if (!needle) return true;
    const haystack = [
      document.display_name,
      document.original_filename,
      document.document_type,
      document.description ?? "",
      categoryLabel(document.category),
      linkOf(document)?.label ?? "",
    ];
    return haystack.some((value) => value.toLowerCase().includes(needle));
  });
}

export function categoryCounts(documents: readonly DocumentResponse[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const document of documents) counts.set(document.category, (counts.get(document.category) ?? 0) + 1);
  return counts;
}

/** The name shown for an uploader, or a plain fallback when the team directory does not list them. */
export function uploaderName(userId: string | null, names: ReadonlyMap<string, string>): string {
  if (!userId) return "Not recorded";
  return names.get(userId) ?? "Unknown user";
}
