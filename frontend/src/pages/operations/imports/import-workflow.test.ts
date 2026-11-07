import { describe, expect, it } from "vitest";

import type { ImportValidationErrorDetail, ImportValidationResult } from "../../../services/importApi";
import {
  canConfirmImport,
  countsFromResult,
  groupErrors,
  hasRequiredMapping,
  importStatusLabel,
  readImportHistory,
  rowsNotImported,
  upsertHistory,
  validateImportFile,
  writeImportHistory,
  IMPORT_HISTORY_KEY,
  type ImportHistoryEntry,
} from "./import-workflow";

const entry = (batchId: string, status = "pending"): ImportHistoryEntry => ({
  batchId,
  sourceFilename: `${batchId}.csv`,
  sourceFormat: "csv",
  startedAt: "2026-11-07T10:00:00Z",
  status,
  counts: null,
  completedAt: null,
});

const validation = (overrides: Partial<ImportValidationResult> = {}): ImportValidationResult => ({
  import_batch_id: "b1",
  source_filename: "contacts.csv",
  source_format: "csv",
  worksheet_name: null,
  status: "pending",
  total_rows: 10,
  valid_rows: 7,
  invalid_rows: 2,
  skipped_rows: 1,
  errors: [],
  error_limit: 100,
  errors_truncated: false,
  contacts_created: 0,
  ...overrides,
});

describe("import file rules", () => {
  it("accepts CSV and XLSX up to the limit, and explains what is refused", () => {
    expect(validateImportFile({ name: "contacts.csv", size: 1000 })).toBeNull();
    expect(validateImportFile({ name: "CONTACTS.XLSX", size: 1000 })).toBeNull();
    expect(validateImportFile({ name: "contacts.pdf", size: 1000 })).toContain("CSV or XLSX");
    expect(validateImportFile({ name: "empty.csv", size: 0 })).toBe("The selected file is empty.");
    expect(validateImportFile({ name: "big.csv", size: 11 * 1024 * 1024 })).toContain("10 MB");
  });
});

describe("import validation results", () => {
  it("requires a first-name column before the file can be validated", () => {
    const column = (suggested: string | null) => ({ index: 0, source_name: "x", display_name: "x", suggested_field: suggested });
    expect(hasRequiredMapping({ columns: [column("first_name")] })).toBe(true);
    expect(hasRequiredMapping({ columns: [column("email")] })).toBe(false);
  });

  it("keeps duplicates apart from other invalid values", () => {
    const errors: ImportValidationErrorDetail[] = [
      { row_number: 2, field: "email", code: "duplicate", message: "exists" },
      { row_number: 3, field: "phone", code: "invalid", message: "bad" },
    ];
    const groups = groupErrors(errors);
    expect(groups.duplicates).toHaveLength(1);
    expect(groups.invalid[0].row_number).toBe(3);
  });

  it("only allows confirming when at least one row is valid, and never after processing", () => {
    expect(canConfirmImport(validation(), false)).toBe(true);
    expect(canConfirmImport(validation({ valid_rows: 0 }), false)).toBe(false);
    expect(canConfirmImport(validation(), true)).toBe(false);
    expect(rowsNotImported(validation())).toBe(3);
  });

  it("reports counts exactly as the server saved them", () => {
    expect(countsFromResult({ total_rows: 5, successful_rows: 3, failed_rows: 1, skipped_rows: 1 })).toEqual({
      total: 5,
      successful: 3,
      failed: 1,
      skipped: 1,
    });
    expect(importStatusLabel("completed_with_errors")).toBe("Completed with errors");
    expect(importStatusLabel("some_new_state")).toBe("some new state");
  });
});

describe("per-device import history", () => {
  it("remembers the batches this browser started, newest first, without duplicates", () => {
    const first = upsertHistory([], entry("a"));
    const second = upsertHistory(first, entry("b"));
    const updated = upsertHistory(second, { ...entry("a"), status: "completed" });
    expect(updated.map((item) => item.batchId)).toEqual(["a", "b"]);
    expect(updated[0].status).toBe("completed");
  });

  it("round-trips through storage and ignores damaged data", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    };
    writeImportHistory([entry("a")], storage);
    expect(store.has(IMPORT_HISTORY_KEY)).toBe(true);
    expect(readImportHistory(storage).map((item) => item.batchId)).toEqual(["a"]);

    store.set(IMPORT_HISTORY_KEY, "{not json");
    expect(readImportHistory(storage)).toEqual([]);
    store.set(IMPORT_HISTORY_KEY, JSON.stringify([{ batchId: 1 }]));
    expect(readImportHistory(storage)).toEqual([]);
  });
});
