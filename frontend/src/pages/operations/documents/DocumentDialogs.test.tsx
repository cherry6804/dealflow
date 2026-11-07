import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { documentApi, type DocumentResponse } from "../../../services/documentApi";
import { DocumentDetailDialog } from "./DocumentDetailDialog";
import { DocumentUploadDialog } from "./DocumentUploadDialog";
import type { RecordOptions } from "./document-lookups";

vi.mock("../../../services/documentApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../services/documentApi")>();
  return {
    ...actual,
    documentApi: {
      list: vi.fn(),
      upload: vi.fn(),
      updateAssociation: vi.fn(),
      download: vi.fn(),
      fetchFile: vi.fn(),
    },
  };
});

const api = vi.mocked(documentApi);

const options: RecordOptions = {
  lead: [{ value: "lead-1", label: "Asha Rao" }],
  property: [{ value: "prop-1", label: "Sea View, Nellore" }],
  deal: [],
};

function doc(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: "d1",
    organization_id: "o1",
    lead_id: null,
    property_id: null,
    deal_id: null,
    original_filename: "qa-title.pdf",
    display_name: "QA title deed",
    description: null,
    category: "OWNERSHIP_TITLE",
    document_type: "Title deed",
    content_type: "application/pdf",
    file_extension: ".pdf",
    file_size_bytes: 4096,
    checksum_sha256: null,
    access_classification: "INTERNAL",
    status: "AVAILABLE",
    uploaded_by_user_id: null,
    uploaded_at: "2026-11-01T10:00:00Z",
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    ...overrides,
  };
}

function fileInput(): HTMLInputElement {
  return document.querySelector("#document-upload-form input[type=file]") as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchFile.mockResolvedValue(new Blob(["x"], { type: "application/pdf" }));
  if (!("createObjectURL" in URL)) {
    Object.defineProperty(URL, "createObjectURL", { value: () => "blob:qa", configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: () => undefined, configurable: true });
  }
});

describe("DocumentUploadDialog", () => {
  it("refuses an unsupported file before uploading anything", async () => {
    render(<DocumentUploadDialog recordOptions={options} onClose={vi.fn()} onUploaded={vi.fn()} />);
    fireEvent.change(fileInput(), { target: { files: [new File(["x"], "bad.exe", { type: "application/octet-stream" })] } });

    expect(await screen.findByText(/Unsupported file type/)).toBeTruthy();
    fireEvent.submit(document.getElementById("document-upload-form") as HTMLFormElement);
    expect(api.upload).not.toHaveBeenCalled();
  });

  it("uploads the file with its metadata, then links it to the chosen record", async () => {
    api.upload.mockResolvedValue(doc({ id: "new-1", display_name: "QA title deed" }));
    api.updateAssociation.mockResolvedValue(doc({ id: "new-1", property_id: "prop-1" }));
    const onUploaded = vi.fn();
    render(<DocumentUploadDialog recordOptions={options} onClose={vi.fn()} onUploaded={onUploaded} />);

    fireEvent.change(fileInput(), { target: { files: [new File(["%PDF"], "qa-title.pdf", { type: "application/pdf" })] } });
    fireEvent.change(screen.getByLabelText(/Category/), { target: { value: "OWNERSHIP_TITLE" } });
    fireEvent.change(screen.getByLabelText(/Link to a record/), { target: { value: "property" } });
    fireEvent.change(screen.getByLabelText(/^Record$/), { target: { value: "prop-1" } });
    fireEvent.submit(document.getElementById("document-upload-form") as HTMLFormElement);

    await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(1));
    const request = api.upload.mock.calls[0][0];
    expect(request.category).toBe("OWNERSHIP_TITLE");
    expect(request.accessClassification).toBe("INTERNAL");
    await waitFor(() => expect(api.updateAssociation).toHaveBeenCalledWith("new-1", { record_type: "property", record_id: "prop-1" }));
    expect(onUploaded).toHaveBeenCalledWith('"QA title deed" was added and linked to a property.');
  });

  it("keeps the stored file and says so when the link fails", async () => {
    api.upload.mockResolvedValue(doc({ id: "new-2" }));
    api.updateAssociation.mockRejectedValue(new Error("Business record not found."));
    const onUploaded = vi.fn();
    render(<DocumentUploadDialog recordOptions={options} onClose={vi.fn()} onUploaded={onUploaded} />);

    fireEvent.change(fileInput(), { target: { files: [new File(["hi"], "note.txt", { type: "text/plain" })] } });
    fireEvent.change(screen.getByLabelText(/Link to a record/), { target: { value: "lead" } });
    fireEvent.change(screen.getByLabelText(/^Record$/), { target: { value: "lead-1" } });
    fireEvent.submit(document.getElementById("document-upload-form") as HTMLFormElement);

    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(onUploaded.mock.calls[0][0]).toContain("was added, but linking it failed");
  });

  it("requires a record when a link type is chosen", async () => {
    render(<DocumentUploadDialog recordOptions={options} onClose={vi.fn()} onUploaded={vi.fn()} />);
    fireEvent.change(fileInput(), { target: { files: [new File(["hi"], "note.txt", { type: "text/plain" })] } });
    fireEvent.change(screen.getByLabelText(/Link to a record/), { target: { value: "deal" } });
    fireEvent.submit(document.getElementById("document-upload-form") as HTMLFormElement);
    expect(await screen.findByText("Choose the record to link, or leave the link empty.")).toBeTruthy();
    expect(api.upload).not.toHaveBeenCalled();
  });
});

describe("DocumentDetailDialog", () => {
  it("removes the link only after confirmation, and keeps the file", async () => {
    api.updateAssociation.mockResolvedValue(doc({ property_id: null }));
    const onChanged = vi.fn();
    render(
      <DocumentDetailDialog
        document={doc({ property_id: "prop-1" })}
        link={{ type: "property", id: "prop-1", label: "Sea View, Nellore" }}
        uploaderName="Charan Appala"
        recordOptions={options}
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Remove link" }));
    const confirm = screen.getByRole("heading", { name: "Remove link?" }).closest("dialog") as HTMLElement;
    expect(within(confirm).getByText(/The file stays in the library/)).toBeTruthy();
    expect(api.updateAssociation).not.toHaveBeenCalled();

    fireEvent.click(within(confirm).getByRole("button", { name: "Remove link" }));
    await waitFor(() => expect(api.updateAssociation).toHaveBeenCalledWith("d1", { record_type: null, record_id: null }));
    expect(api.download).not.toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalledWith("The link was removed. The file is still in the library.");
  });

  it("does not load a preview for formats the browser cannot show", async () => {
    render(
      <DocumentDetailDialog
        document={doc({ original_filename: "terms.docx", file_extension: ".docx", display_name: "Terms" })}
        link={null}
        uploaderName="Unknown user"
        recordOptions={options}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByText(/Preview is not available for DOCX files/)).toBeTruthy();
    expect(api.fetchFile).not.toHaveBeenCalled();
  });

  it("shows metadata as read-only and states that deleting files is not available", async () => {
    render(
      <DocumentDetailDialog
        document={doc()}
        link={null}
        uploaderName="Charan Appala"
        recordOptions={options}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByText(/Deleting a file is not available here/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
  });
});
