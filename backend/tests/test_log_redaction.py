"""DFR1-050: secrets and sensitive content are not written to logs through tracebacks.

Tracebacks can carry database statement parameters and storage keys, which are record values. Application code
therefore logs failures as messages only. This test fails if traceback logging returns anywhere in the backend.
"""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN = ("logger.exception(", "exc_info=True")


def test_application_code_never_logs_tracebacks() -> None:
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN:
            if pattern in text:
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}: {pattern}")
    assert offenders == [], "Tracebacks can carry record values. Log the message only: " + ", ".join(offenders)
