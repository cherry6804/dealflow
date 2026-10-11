
import { api } from "../lib/api";

const API_BASE_PATH = "/imports";

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

export interface ImportValidationErrorDetail {
  row_number: number;
  field: string;
  code: string;
  message: string;
}

export interface ImportValidationResult {
  import_batch_id: string;
  source_filename: string;
  source_format: string;
  worksheet_name: string | null;
  status: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  skipped_rows: number;
  errors: ImportValidationErrorDetail[];
  error_limit: number;
  errors_truncated: boolean;
  contacts_created: number;
}

export interface ImportProcessingResult {
  import_batch_id: string;
  source_filename: string;
  source_format: string;
  worksheet_name: string | null;
  status: string;
  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  skipped_rows: number;
  contacts_created: number;
  errors: ImportValidationErrorDetail[];
  error_limit: number;
  errors_truncated: boolean;
}

export interface ImportResult {
  import_batch_id: string;
  source_filename: string;
  source_format: string;
  status: string;
  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  skipped_rows: number;
  contacts_created: number;
  errors: ImportValidationErrorDetail[];
  error_limit: number;
  errors_truncated: boolean;
}

export const importApi = {
  async upload(file: File): Promise<ImportBatch> {
    const formData = new FormData();
    formData.append("file", file);

    return api.post<ImportBatch>(`${API_BASE_PATH}/uploads`, formData);
  },

  async preview(importBatchId: string): Promise<ImportPreview> {
    return api.get<ImportPreview>(
      `${API_BASE_PATH}/${encodeURIComponent(importBatchId)}/preview`,
    );
  },

  async validate(
    importBatchId: string,
  ): Promise<ImportValidationResult> {
    return api.get<ImportValidationResult>(
      `${API_BASE_PATH}/${encodeURIComponent(importBatchId)}/validation`,
    );
  },

  async process(
    importBatchId: string,
  ): Promise<ImportProcessingResult> {
    return api.post<ImportProcessingResult>(
      `${API_BASE_PATH}/${encodeURIComponent(importBatchId)}/process`,
    );
  },

  async result(importBatchId: string): Promise<ImportResult> {
    return api.get<ImportResult>(
      `${API_BASE_PATH}/${encodeURIComponent(importBatchId)}/result`,
    );
  },

  async downloadErrors(importBatchId: string): Promise<void> {
    return api.download(
      `${API_BASE_PATH}/${encodeURIComponent(importBatchId)}/errors.csv`,
      `import-${importBatchId}-errors.csv`,
    );
  },
};
