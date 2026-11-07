import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api";
import { importApi, type ImportPreview, type ImportResult, type ImportValidationResult } from "../../../services/importApi";
import { ImportWizardDialog } from "./ImportWizardDialog";

vi.mock("../../../services/importApi", () => ({
  importApi: {
    upload: vi.fn(),
    preview: vi.fn(),
    validate: vi.fn(),
    process: vi.fn(),
    result: vi.fn(),
    downloadErrors: vi.fn(),
  },
}));

const api = vi.mocked(importApi);

function preview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    import_batch_id: "b1",
    source_filename: "contacts.csv",
    source_format: "csv",
    worksheet_name: null,
    columns: [
      { index: 0, source_name: "First name", display_name: "First name", suggested_field: "first_name" },
      { index: 1, source_name: "Email", display_name: "Email", suggested_field: "email" },
    ],
    suggested_target_fields: [
      { value: "first_name", label: "First name" },
      { value: "email", label: "Email" },
    ],
    preview_rows: [{ "First name": "Asha", Email: "asha@example.com" }],
    preview_row_limit: 10,
    has_more_rows: false,
    contacts_created: 0,
    ...overrides,
  };
}

function validation(overrides: Partial<ImportValidationResult> = {}): ImportValidationResult {
  return {
    import_batch_id: "b1",
    source_filename: "contacts.csv",
    source_format: "csv",
    worksheet_name: null,
    status: "pending",
    total_rows: 3,
    valid_rows: 2,
    invalid_rows: 1,
    skipped_rows: 0,
    errors: [{ row_number: 3, field: "email", code: "duplicate", message: "A contact with this email already exists." }],
    error_limit: 100,
    errors_truncated: false,
    contacts_created: 0,
    ...overrides,
  };
}

function result(overrides: Partial<ImportResult> = {}): ImportResult {
  return {
    import_batch_id: "b1",
    source_filename: "contacts.csv",
    source_format: "csv",
    status: "completed_with_errors",
    total_rows: 3,
    processed_rows: 3,
    successful_rows: 2,
    failed_rows: 1,
    skipped_rows: 0,
    contacts_created: 2,
    errors: [{ row_number: 3, field: "email", code: "duplicate", message: "A contact with this email already exists." }],
    error_limit: 100,
    errors_truncated: false,
    ...overrides,
  };
}

function chooseFile() {
  const input = document.querySelector("input[type=file]") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["First name,Email\nAsha,asha@example.com"], "contacts.csv", { type: "text/csv" })] } });
}

function dialog(): HTMLElement {
  return screen.getByRole("heading", { name: "Import 2 contact(s)?" }).closest("dialog") as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ImportWizardDialog", () => {
  it("runs the guided import, and creates contacts only after confirmation", async () => {
    api.upload.mockResolvedValue({ id: "b1", source_filename: "contacts.csv", source_format: "csv", status: "pending", total_rows: 0, processed_rows: 0, successful_rows: 0, failed_rows: 0, skipped_rows: 0 });
    api.preview.mockResolvedValue(preview());
    api.validate.mockResolvedValue(validation());
    api.process.mockResolvedValue({ ...result(), processed_rows: 3, worksheet_name: null } as never);
    api.result.mockResolvedValue(result());
    const onChanged = vi.fn();
    render(<ImportWizardDialog onClose={vi.fn()} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /Contacts/ }));
    chooseFile();
    fireEvent.click(await screen.findByRole("button", { name: "Upload and read file" }));

    expect(await screen.findByRole("button", { name: "Continue to preview" })).toBeTruthy();
    expect(api.process).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Continue to preview" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue to validation" }));
    fireEvent.click(screen.getByRole("button", { name: "Validate rows" }));

    expect(await screen.findByText("Duplicates")).toBeTruthy();
    expect(screen.getAllByText("Duplicate").length).toBeGreaterThan(0);
    expect(api.process).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Review import" }));
    fireEvent.click(screen.getByRole("button", { name: "Import 2 contact(s)" }));
    expect(api.process).not.toHaveBeenCalled();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Import contacts" }));

    await waitFor(() => expect(api.process).toHaveBeenCalledWith("b1"));
    expect(await screen.findByRole("heading", { name: "Import report" })).toBeTruthy();
    expect(screen.getByText("Completed with errors")).toBeTruthy();
    expect(onChanged).toHaveBeenLastCalledWith(expect.objectContaining({ batchId: "b1", status: "completed_with_errors" }));
  });

  it("blocks the import when the first-name column is missing", async () => {
    api.upload.mockResolvedValue({ id: "b2", source_filename: "contacts.csv", source_format: "csv", status: "pending", total_rows: 0, processed_rows: 0, successful_rows: 0, failed_rows: 0, skipped_rows: 0 });
    api.preview.mockResolvedValue(
      preview({ columns: [{ index: 0, source_name: "Email", display_name: "Email", suggested_field: "email" }] }),
    );
    render(<ImportWizardDialog onClose={vi.fn()} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Contacts/ }));
    chooseFile();
    fireEvent.click(await screen.findByRole("button", { name: "Upload and read file" }));

    expect(await screen.findByText(/A column named First name is required/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue to preview" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a validation refusal as the server states it, and imports nothing", async () => {
    api.upload.mockResolvedValue({ id: "b3", source_filename: "contacts.csv", source_format: "csv", status: "pending", total_rows: 0, processed_rows: 0, successful_rows: 0, failed_rows: 0, skipped_rows: 0 });
    api.preview.mockResolvedValue(preview());
    api.validate.mockRejectedValue(new ApiError("Multiple source columns match these contact fields: email.", 422));
    render(<ImportWizardDialog onClose={vi.fn()} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Contacts/ }));
    chooseFile();
    fireEvent.click(await screen.findByRole("button", { name: "Upload and read file" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to preview" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue to validation" }));
    fireEvent.click(screen.getByRole("button", { name: "Validate rows" }));

    expect(await screen.findByText("Multiple source columns match these contact fields: email.")).toBeTruthy();
    expect(api.process).not.toHaveBeenCalled();
  });

  it("does not run an import twice: a batch that was already processed opens its saved report", async () => {
    api.result.mockResolvedValue(result({ status: "completed" }));
    api.process.mockRejectedValue(new ApiError("Only pending import batches can be processed.", 409));
    render(<ImportWizardDialog batchId="b9" onClose={vi.fn()} onChanged={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Import report" })).toBeTruthy();
    expect(api.process).not.toHaveBeenCalled();
    expect(screen.getByText("Completed")).toBeTruthy();
  });

  it("explains a pending batch that was read but never imported", async () => {
    api.result.mockResolvedValue(result({ status: "pending", successful_rows: 0, failed_rows: 0, errors: [] }));
    render(<ImportWizardDialog batchId="b8" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByText(/was read but not imported/)).toBeTruthy();
  });
});
