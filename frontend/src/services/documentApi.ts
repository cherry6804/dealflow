
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
  async upload(
    request: DocumentUploadRequest,
  ): Promise<DocumentResponse> {
    const formData = new FormData();

    formData.append("file", request.file);
    formData.append("display_name", request.displayName.trim());
    formData.append("description", request.description.trim());
    formData.append("category", request.category);
    formData.append("document_type", request.documentType.trim());
    formData.append(
      "access_classification",
      request.accessClassification,
    );

    return api.post<DocumentResponse>("/documents/uploads", formData);
  },
};
