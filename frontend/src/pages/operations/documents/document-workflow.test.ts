import { describe, expect, it } from "vitest";

import type { DocumentResponse } from "../../../services/documentApi";
import {
  categoryCounts,
  fileFormat,
  filterDocuments,
  formatFileSize,
  linkedRecord,
  previewKind,
  uploaderName,
  type LinkLookup,
} from "./document-workflow";

function doc(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: "d1",
    organization_id: "o1",
    lead_id: null,
    property_id: null,
    deal_id: null,
    original_filename: "sale-agreement.pdf",
    display_name: "Sale agreement",
    description: null,
    category: "AGREEMENT",
    document_type: "Sale agreement",
    content_type: "application/pdf",
    file_extension: ".pdf",
    file_size_bytes: 2048,
    checksum_sha256: null,
    access_classification: "CONFIDENTIAL",
    status: "AVAILABLE",
    uploaded_by_user_id: null,
    uploaded_at: "2026-11-01T10:00:00Z",
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-02T10:00:00Z",
    ...overrides,
  };
}

const lookup: LinkLookup = {
  leads: new Map([["lead-1", "Asha Rao"]]),
  properties: new Map([["prop-1", "Sea View, Nellore"]]),
  deals: new Map([["deal-1", "Ravi · Sea View"]]),
};

describe("document rules", () => {
  it("shows the link of whichever record the document is attached to", () => {
    expect(linkedRecord(doc({ lead_id: "lead-1" }), lookup)).toEqual({ type: "lead", id: "lead-1", label: "Asha Rao" });
    expect(linkedRecord(doc({ property_id: "prop-1" }), lookup)?.label).toBe("Sea View, Nellore");
    expect(linkedRecord(doc({ deal_id: "missing" }), lookup)?.label).toBe("Deal unavailable");
    expect(linkedRecord(doc(), lookup)).toBeNull();
  });

  it("filters by search, category and link without losing documents", () => {
    const docs = [
      doc({ id: "a", display_name: "Title deed" }),
      doc({ id: "b", category: "FINANCIAL", display_name: "Receipt", lead_id: "lead-1" }),
      doc({ id: "c", category: "OTHER", original_filename: "plan.png", document_type: "Floor plan" }),
    ];
    const byLink = (document: DocumentResponse) => linkedRecord(document, lookup);

    expect(filterDocuments(docs, { search: "asha", category: null, link: null }, byLink).map((item) => item.id)).toEqual(["b"]);
    expect(filterDocuments(docs, { search: "floor", category: null, link: null }, byLink).map((item) => item.id)).toEqual(["c"]);
    expect(filterDocuments(docs, { search: "", category: "FINANCIAL", link: null }, byLink).map((item) => item.id)).toEqual(["b"]);
    expect(filterDocuments(docs, { search: "", category: null, link: "unlinked" }, byLink).map((item) => item.id)).toEqual(["a", "c"]);
    expect(filterDocuments(docs, { search: "zzz", category: null, link: null }, byLink)).toEqual([]);
  });

  it("counts documents per category", () => {
    const counts = categoryCounts([doc(), doc({ id: "x" }), doc({ id: "y", category: "OTHER" })]);
    expect(counts.get("AGREEMENT")).toBe(2);
    expect(counts.get("OTHER")).toBe(1);
    expect(counts.get("DEAL")).toBeUndefined();
  });

  it("previews only formats the browser can show, and everything else is download only", () => {
    expect(previewKind(doc())).toBe("pdf");
    expect(previewKind(doc({ file_extension: ".JPG", original_filename: "a.JPG" }))).toBe("image");
    expect(previewKind(doc({ file_extension: ".csv", original_filename: "a.csv" }))).toBe("text");
    expect(previewKind(doc({ file_extension: ".docx", original_filename: "a.docx" }))).toBe("none");
  });

  it("formats sizes and file formats for display", () => {
    expect(formatFileSize(null)).toBe("—");
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(fileFormat(doc({ file_extension: ".xlsx", original_filename: "x.xlsx" }))).toBe("XLSX");
  });

  it("names the uploader from the directory, and never invents a name", () => {
    const names = new Map([["u1", "Charan Appala"]]);
    expect(uploaderName("u1", names)).toBe("Charan Appala");
    expect(uploaderName("u2", names)).toBe("Unknown user");
    expect(uploaderName(null, names)).toBe("Not recorded");
  });
});
