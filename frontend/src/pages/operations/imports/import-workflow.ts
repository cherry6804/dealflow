import type { ImportPreview, ImportResult, ImportValidationErrorDetail, ImportValidationResult } from "../../../services/importApi";

/**
 * Import rules for the import center. The API imports contacts only, from CSV or XLSX files, and maps columns by header name.
 * Nothing here adds a capability the backend does not have.
 */

export const IMPORT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
export const IMPORT_ALLOWED_EXTENSIONS = [".csv", ".xlsx"] as const;

export interface ImportDataType {
  id: "contacts" | "customers" | "leads" | "properties" | "requirements" | "deals";
  label: string;
  available: boolean;
  description: string;
}

export const IMPORT_DATA_TYPES: readonly ImportDataType[] = [
  {
    id: "contacts",
    label: "Contacts",
    available: true,
    description: "Names, email addresses and phone numbers. Each valid row creates one contact.",
  },
  { id: "customers", label: "Customers", available: false, description: "Not available for import yet." },
  { id: "leads", label: "Leads", available: false, description: "Not available for import yet." },
  { id: "properties", label: "Properties", available: false, description: "Not available for import yet." },
  { id: "requirements", label: "Requirements", available: false, description: "Not available for import yet." },
  { id: "deals", label: "Deals", available: false, description: "Not available for import yet." },
];

export function fileExtension(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
}

/** Client-side checks that mirror the server. The server still decides; a refusal is shown as the server states it. */
export function validateImportFile(file: { name: string; size: number }): string | null {
  const extension = fileExtension(file.name);
  if (!(IMPORT_ALLOWED_EXTENSIONS as readonly string[]).includes(extension)) {
    return "Choose a CSV or XLSX file. Other formats cannot be imported.";
  }
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > IMPORT_MAX_FILE_SIZE_BYTES) return "The selected file is larger than the 10 MB import limit.";
  return null;
}

export const IMPORT_STATUS_LABELS: Readonly<Record<string, string>> = {
  pending: "Ready to process",
  processing: "Processing",
  completed: "Completed",
  completed_with_errors: "Completed with errors",
  failed: "Failed",
};

export function importStatusLabel(status: string): string {
  return IMPORT_STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

export function importStatusTone(status: string): "success" | "danger" | "pending" | "neutral" {
  if (status === "completed") return "success";
  if (status === "completed_with_errors" || status === "failed") return "danger";
  if (status === "pending" || status === "processing") return "pending";
  return "neutral";
}

/** Whether the required first-name column was matched. Without it the file cannot be validated. */
export function hasRequiredMapping(preview: Pick<ImportPreview, "columns">): boolean {
  return preview.columns.some((column) => column.suggested_field === "first_name");
}

export interface ErrorGroups {
  duplicates: ImportValidationErrorDetail[];
  invalid: ImportValidationErrorDetail[];
}

/** Separates duplicate rows from other invalid values, so duplicates are never mistaken for bad data. */
export function groupErrors(errors: readonly ImportValidationErrorDetail[]): ErrorGroups {
  return {
    duplicates: errors.filter((error) => error.code === "duplicate"),
    invalid: errors.filter((error) => error.code !== "duplicate"),
  };
}

export interface ImportCounts {
  total: number;
  successful: number;
  failed: number;
  skipped: number;
}

export function countsFromValidation(result: ImportValidationResult): ImportCounts & { valid: number } {
  return {
    total: result.total_rows,
    successful: 0,
    failed: result.invalid_rows,
    skipped: result.skipped_rows,
    valid: result.valid_rows,
  };
}

export function countsFromResult(result: Pick<ImportResult, "total_rows" | "successful_rows" | "failed_rows" | "skipped_rows">): ImportCounts {
  return {
    total: result.total_rows,
    successful: result.successful_rows,
    failed: result.failed_rows,
    skipped: result.skipped_rows,
  };
}

/** Rows that will not become contacts, with the reason given by the validation result. */
export function rowsNotImported(result: Pick<ImportValidationResult, "invalid_rows" | "skipped_rows">): number {
  return result.invalid_rows + result.skipped_rows;
}

export function canConfirmImport(result: Pick<ImportValidationResult, "valid_rows">, processed: boolean): boolean {
  return !processed && result.valid_rows > 0;
}

// ---- Per-device import history -------------------------------------------------------------------------------------------------

/**
 * The API has no list of past imports, so this browser remembers the batches it started. It is a convenience only: opening an entry
 * asks the server for that batch, and the server decides whether the entry is still readable.
 */
export const IMPORT_HISTORY_KEY = "dealflow.import-history.v1";
const MAX_HISTORY_ENTRIES = 25;

export interface ImportHistoryEntry {
  batchId: string;
  sourceFilename: string;
  sourceFormat: string;
  startedAt: string;
  /** Last status and counts this browser saw. Refreshed from the server on request. */
  status: string;
  counts: ImportCounts | null;
  completedAt: string | null;
}

export function readImportHistory(storage: Pick<Storage, "getItem"> | null = safeLocalStorage()): ImportHistoryEntry[] {
  try {
    const raw = storage?.getItem(IMPORT_HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isHistoryEntry).slice(0, MAX_HISTORY_ENTRIES);
  } catch {
    return [];
  }
}

export function writeImportHistory(
  entries: readonly ImportHistoryEntry[],
  storage: Pick<Storage, "setItem"> | null = safeLocalStorage(),
): void {
  try {
    storage?.setItem(IMPORT_HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY_ENTRIES)));
  } catch {
    // Storage can be full or blocked. The import still works; only the convenience list is lost.
  }
}

export function upsertHistory(entries: readonly ImportHistoryEntry[], entry: ImportHistoryEntry): ImportHistoryEntry[] {
  const rest = entries.filter((item) => item.batchId !== entry.batchId);
  return [entry, ...rest].slice(0, MAX_HISTORY_ENTRIES);
}

function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function isHistoryEntry(value: unknown): value is ImportHistoryEntry {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.batchId === "string" &&
    typeof entry.sourceFilename === "string" &&
    typeof entry.sourceFormat === "string" &&
    typeof entry.startedAt === "string" &&
    typeof entry.status === "string"
  );
}
