import { api } from "../lib/api";

export const DOCUMENT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

export const DOCUMENT_ALLOWED_EXTENSIONS = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".txt",
  ".csv",
  ".docx",
  ".xlsx",
] as const;

export const DOCUMENT_CATEGORIES = [
  { value: "IDENTITY_KYC", label: "Identity / KYC" },
  { value: "OWNERSHIP_TITLE", label: "Ownership / Title" },
  { value: "LEGAL_COMPLIANCE", label: "Legal / Compliance" },
  { value: "PROPERTY_RECORD", label: "Property Record" },
  { value: "MARKETING", label: "Marketing" },
  { value: "AGREEMENT", label: "Agreement" },
  { value: "FINANCIAL", label: "Financial" },
  { value: "CUSTOMER", label: "Customer" },
  { value: "DEAL", label: "Deal" },
  { value: "OTHER", label: "Other" },
] as const;

export const DOCUMENT_ACCESS_CLASSIFICATIONS = [
  { value: "INTERNAL", label: "Internal" },
  { value: "CONFIDENTIAL", label: "Confidential" },
  { value: "RESTRICTED", label: "Restricted" },
  { value: "PUBLIC", label: "Public" },
] as const;

export interface DocumentUploadRequest {
  file: File;
  displayName: string;
  description: string;
  category: string;
  documentType: string;
  accessClassification: string;
}

export interface DocumentResponse {
  id: string;
  organization_id: string;
  original_filename: string;
  display_name: string;
  description: string | null;
  category: string;
  document_type: string;
  content_type: string | null;
  file_extension: string | null;
  file_size_bytes: number | null;
  checksum_sha256: string | null;
  access_classification: string;
  status: string;
  uploaded_by_user_id: string | null;
  uploaded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: DocumentResponse[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface DocumentListParams {
  page?: number;
  pageSize?: number;
  category?: string;
}

function getExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

export function validateDocumentFile(file: File): string | null {
  const extension = getExtension(file.name);

  if (
    !DOCUMENT_ALLOWED_EXTENSIONS.some(
      (allowedExtension) => allowedExtension === extension,
    )
  ) {
    return "Unsupported file type. Choose a PDF, PNG, JPG, TXT, CSV, DOCX or XLSX file.";
  }

  if (file.size === 0) {
    return "The selected file is empty.";
  }

  if (file.size > DOCUMENT_MAX_FILE_SIZE_BYTES) {
    return "The selected file exceeds the 10 MB upload limit.";
  }

  return null;
}

export const documentApi = {
  async list(
    params: DocumentListParams = {},
  ): Promise<DocumentListResponse> {
    const page = params.page ?? 1;
    const pageSize = params.pageSize ?? 20;

    if (!Number.isInteger(page) || page < 1) {
      throw new Error("Page must be a positive integer.");
    }

    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new Error("Page size must be between 1 and 100.");
    }

    const query = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });

    if (params.category?.trim()) {
      query.set("category", params.category.trim());
    }

    return api.get<DocumentListResponse>(`/documents?${query.toString()}`);
  },

  async upload(request: DocumentUploadRequest): Promise<DocumentResponse> {
    const formData = new FormData();
    formData.append("file", request.file);
    formData.append("display_name", request.displayName.trim());
    formData.append("description", request.description.trim());
    formData.append("category", request.category);
    formData.append("document_type", request.documentType.trim());
    formData.append("access_classification", request.accessClassification);

    return api.post<DocumentResponse>("/documents/uploads", formData);
  },

  async download(documentId: string, filename: string): Promise<void> {
    if (!documentId.trim()) {
      throw new Error("A document ID is required to download a file.");
    }

    const safeFilename = filename.trim().replace(/[\r\n]/g, "") || "document";

    return api.download(
      `/documents/${encodeURIComponent(documentId)}/download`,
      safeFilename,
    );
  },
};
