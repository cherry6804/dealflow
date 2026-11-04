"""Safe text extraction for knowledge ingestion (DFR1-016).

Supported:

- plain text, Markdown and CSV, decoded as strict UTF-8;
- XLSX, through ``openpyxl``, which the project already declares;
- DOCX, through the standard library: the package is read as a ZIP, and only ``word/document.xml`` is parsed;
- PDF, through ``pypdf`` (pinned in ``pyproject.toml`` and ``uv.lock``, see ``docs/development/python-dependency-register.md``).
  Text only; encrypted, malformed and over-page-limit files are refused.

Not supported: legacy Office formats and presentations, which are refused with ``format_not_supported``.

Limits, all enforced before parsing: the stored file size, the ZIP member count and total uncompressed size, the XML size,
the number of sheets, rows and columns, and the total characters returned. XML that declares a DTD or entities is refused,
which closes off entity-expansion attacks without a third-party library.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

TEXT_TYPES: frozenset[str] = frozenset({"text/plain", "text/markdown", "text/csv"})
PDF_TYPE = "application/pdf"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_TYPES: frozenset[str] = TEXT_TYPES | {PDF_TYPE, XLSX_TYPE, DOCX_TYPE}

MAX_EXTRACTED_CHARACTERS = 200_000
MAX_ZIP_MEMBERS = 500
MAX_ZIP_UNCOMPRESSED_BYTES = 20_000_000
MAX_XML_BYTES = 10_000_000
MAX_SHEETS = 10
MAX_ROWS = 5_000
MAX_COLUMNS = 50
MAX_PDF_PAGES = 100
# Recovery and cross-reference limits passed to pypdf, so a damaged or hostile file cannot make it scan without bound.
PDF_ROOT_RECOVERY_LIMIT = 1_000
PDF_XREF_MAX_ENTRIES = 100_000

REASON_FORMAT = "format_not_supported"
REASON_NOT_TEXT = "content_not_utf8_text"
REASON_UNSAFE = "unsafe_document_structure"
REASON_UNREADABLE = "content_unreadable"
REASON_TOO_LARGE = "content_too_large"
REASON_ENCRYPTED = "encrypted_document"
REASON_PAGE_LIMIT = "page_limit_exceeded"

_DOCX_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_DOCX_PARAGRAPH = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"


class ExtractionError(Exception):
    """Extraction refused. ``reason`` is a stable code and never contains document content."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def extract_text(content_type: str, raw: bytes) -> str:
    """Return the text of a supported document, or raise ``ExtractionError``."""
    if content_type in TEXT_TYPES:
        return _decode_text(raw)
    if content_type == PDF_TYPE:
        return _extract_pdf(raw)
    if content_type == XLSX_TYPE:
        return _extract_xlsx(raw)
    if content_type == DOCX_TYPE:
        return _extract_docx(raw)
    raise ExtractionError(REASON_FORMAT)


def _decode_text(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(REASON_NOT_TEXT) from exc
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise ExtractionError(REASON_TOO_LARGE)
    return text


def _extract_xlsx(raw: bytes) -> str:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError, TypeError, OSError) as exc:
        raise ExtractionError(REASON_UNREADABLE) from exc
    lines: list[str] = []
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets):
            if sheet_index >= MAX_SHEETS:
                break
            lines.append(f"Sheet: {sheet.title}")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= MAX_ROWS:
                    break
                cells = ["" if value is None else str(value) for value in list(row)[:MAX_COLUMNS]]
                if any(cells):
                    lines.append("\t".join(cells))
                if sum(len(line) for line in lines) > MAX_EXTRACTED_CHARACTERS:
                    raise ExtractionError(REASON_TOO_LARGE)
    finally:
        workbook.close()
    return "\n".join(lines)


def _extract_docx(raw: bytes) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ExtractionError(REASON_UNREADABLE) from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ExtractionError(REASON_UNSAFE)
        if sum(member.file_size for member in members) > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ExtractionError(REASON_UNSAFE)
        try:
            info = archive.getinfo("word/document.xml")
        except KeyError as exc:
            raise ExtractionError(REASON_UNREADABLE) from exc
        if info.file_size > MAX_XML_BYTES:
            raise ExtractionError(REASON_UNSAFE)
        xml_bytes = archive.read(info)

    upper = xml_bytes[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ExtractionError(REASON_UNSAFE)
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ExtractionError(REASON_UNREADABLE) from exc

    paragraphs: list[str] = []
    for paragraph in root.iter(_DOCX_PARAGRAPH):
        text = "".join(node.text or "" for node in paragraph.iter(_DOCX_TEXT))
        if text.strip():
            paragraphs.append(text)
        if sum(len(item) for item in paragraphs) > MAX_EXTRACTED_CHARACTERS:
            raise ExtractionError(REASON_TOO_LARGE)
    return "\n".join(paragraphs)


def _extract_pdf(raw: bytes) -> str:
    """Extract the text of a PDF. Encrypted files, malformed files and files over the page limit are refused.

    Text only: no annotation, form, script or embedded-file content is read, and nothing in the file is executed.
    """
    try:
        reader = PdfReader(
            io.BytesIO(raw),
            strict=False,
            root_object_recovery_limit=PDF_ROOT_RECOVERY_LIMIT,
            xref_stream_maximum_entries=PDF_XREF_MAX_ENTRIES,
        )
    except (PdfReadError, ValueError, TypeError, KeyError, IndexError, OSError, AssertionError) as exc:
        raise ExtractionError(REASON_UNREADABLE) from exc
    try:
        if reader.is_encrypted:
            raise ExtractionError(REASON_ENCRYPTED)
        page_count = len(reader.pages)
        if page_count == 0:
            raise ExtractionError(REASON_UNREADABLE)
        if page_count > MAX_PDF_PAGES:
            raise ExtractionError(REASON_PAGE_LIMIT)
        lines: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                lines.append(text.strip())
            if sum(len(item) for item in lines) > MAX_EXTRACTED_CHARACTERS:
                raise ExtractionError(REASON_TOO_LARGE)
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, IndexError, OSError, AssertionError) as exc:
        raise ExtractionError(REASON_UNREADABLE) from exc
    return "\n".join(lines)
