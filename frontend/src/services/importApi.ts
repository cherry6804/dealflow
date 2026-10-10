import { api } from "../lib/api";

export interface ImportBatch {
  id: string;
  source_filename: string;
  source_format: string;
  status: string;
  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  skipped_rows: number;
}

export interface ImportPreviewColumn {
  index: number;
  source_name: string;
  display_name: string;
  suggested_field: string | null;
}

export interface ImportPreviewTargetField {
  value: string;
  label: string;
}

export interface ImportPreview {
  import_batch_id: string;
  source_filename: string;
  source_format: string;
  worksheet_name: string | null;
  columns: ImportPreviewColumn[];
  suggested_target_fields: ImportPreviewTargetField[];
  preview_rows: Record<string, string | null>[];
  preview_row_limit: number;
  has_more_rows: boolean;
  contacts_created: number;
}

export const importApi = {
  async upload(file: File): Promise<ImportBatch> {
    const formData = new FormData();
    formData.append("file", file);

    return api.post<ImportBatch>("/imports/uploads", formData);
  },

  async preview(importBatchId: string): Promise<ImportPreview> {
    return api.get<ImportPreview>(
      `/imports/${encodeURIComponent(importBatchId)}/preview`,
    );
  },
};