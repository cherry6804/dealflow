"""Rebuild the ADR register table in docs/adr/README.md from each ADR file.

Titles and statuses are read from the files, so the index cannot drift from
the records it describes.
"""

from __future__ import annotations

import re
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parents[1] / "docs" / "adr"
TABLE_HEADER = "| ADR | Title | Status |"
TABLE_END_MARKER = "New ADRs should be added"

TITLE_PATTERN = re.compile(r"^\\?#\s*ADR-?(\d{4})\s*:?\s*(.+)$", re.MULTILINE)
STATUS_PATTERN = re.compile(
    r"Status\W*:?\W*\s*(Accepted|Proposed|Superseded|Deprecated|Rejected)",
    re.IGNORECASE,
)


def collect_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for path in sorted(ADR_DIR.iterdir()):
        if path.suffix != ".md" or path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        title_match = TITLE_PATTERN.search(text)
        if title_match is None:
            continue
        number = title_match.group(1)
        title = title_match.group(2).replace("\\", "").strip()
        status_match = STATUS_PATTERN.search(text)
        status = status_match.group(1).capitalize() if status_match else "Unknown"
        rows.append((number, title, status))
    return sorted(rows)


def main() -> None:
    readme = ADR_DIR / "README.md"
    content = readme.read_text(encoding="utf-8")
    rows = collect_rows()
    table_lines = [TABLE_HEADER, "|---|---|---|"]
    table_lines += [f"| {number} | {title} | {status} |" for number, title, status in rows]
    table = "\n".join(table_lines) + "\n\n"

    start = content.index(TABLE_HEADER)
    end = content.index(TABLE_END_MARKER)
    readme.write_text(content[:start] + table + content[end:], encoding="utf-8", newline="\n")
    print(f"ADR index rows: {len(rows)}")
    for number, title, status in rows:
        print(f"{number} | {title} | {status}")


if __name__ == "__main__":
    main()
