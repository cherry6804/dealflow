# Python dependency register

Every runtime dependency that handles customer data, with the reason it is there and what was checked. Update this file in
the same change that adds, removes or upgrades a dependency. The lock file (`backend/uv.lock`) is the source of exact versions.

| Package | Declared range | Locked version | Purpose | Added by | Licence (source) | Advisory check |
|---|---|---|---|---|---|---|
| `openpyxl` | `>=3.1.5` | see lock | XLSX text extraction for knowledge ingestion (DFR1-016) | earlier release work | MIT (project metadata) | Not re-checked in this pass |
| `pypdf` | `>=6.21.4,<7.0` | `6.21.4` | PDF text extraction for knowledge ingestion (DFR1-016) | DFR1-016 completion pass, approved by product | BSD-style, per the LICENSE file in the installed distribution. Full text to be reviewed by the approver. | `pip-audit` on `pypdf==6.21.4`: no known vulnerabilities |

## pypdf: how it is used and bounded

- Only text is read. Annotations, forms, JavaScript actions, attachments and embedded files are not read, and nothing in a
  PDF is executed. `tests/test_knowledge_lifecycle.py::test_only_page_text_is_extracted_not_script_or_actions` checks this.
- Encrypted files are refused before any text is read (`encrypted_document`).
- Files with more than 100 pages are refused (`page_limit_exceeded`).
- The reader is given explicit recovery and cross-reference limits (`PDF_ROOT_RECOVERY_LIMIT`, `PDF_XREF_MAX_ENTRIES`).
- The stored file is at most 1 MB (`MAX_DOCUMENT_BYTES`), and extracted text at most 200,000 characters.
- Malformed files are refused as `content_unreadable`. A file that parses to zero pages is also refused.

## Upgrading pypdf

1. Change the range in `backend/pyproject.toml` only if the new major version is reviewed.
2. Run `uv lock --upgrade-package pypdf` from `backend/`.
3. Run `pip-audit` on the new pinned version and record the result here.
4. Run `tests/test_knowledge_lifecycle.py` and `tests/test_knowledge.py`.
