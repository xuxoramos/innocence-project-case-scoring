"""Extract text from an uploaded intake PDF and prefill the common schema.

Offline-only and dependency-free: shells out to poppler's ``pdftotext`` for
digital PDFs and falls back to ``pdftoppm`` + ``tesseract`` for scanned ones, so
no Python PDF/OCR package (and no network) is required. Nothing here invents
content (README v2 §3.2): it lifts literal ``Label: value`` lines that the
reviewer then verifies against the original PDF shown alongside the form, and
keeps anything it cannot confidently place in the intake's ``unmapped`` list.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # noqa: S404 - only ever invoked with fixed, non-shell argv
import tempfile
from pathlib import Path

from .intake.record import IntakeRecord
from .intake.structuring import structure_intake

_PDFTOTEXT = "pdftotext"
_PDFTOPPM = "pdftoppm"
_TESSERACT = "tesseract"

#: Minimum characters of embedded text before we trust the digital layer and
#: skip the (slower, lossier) OCR fallback.
_EMBEDDED_TEXT_FLOOR = 40

#: Cap on subprocess runtime so a pathological file can't hang a request.
_SUBPROCESS_TIMEOUT = 120

#: One ``Label: value`` line. Colon-separated only (the standard intake-form
#: shape); a short label of letters/spaces/basic punctuation, then a non-empty
#: value. Deliberately conservative to avoid lifting prose as false fields.
_PAIR_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /.'&()-]{0,59}?)\s*:\s*(\S.*?)\s*$")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user-controlled binary
        argv, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT
    )


def _embedded_text(pdf_path: Path) -> str:
    """Text from the PDF's digital layer via ``pdftotext`` (empty if none)."""
    if not shutil.which(_PDFTOTEXT):
        return ""
    try:
        proc = _run([_PDFTOTEXT, "-layout", str(pdf_path), "-"])
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _ocr_text(pdf_path: Path) -> str:
    """OCR the rendered pages via ``pdftoppm`` + ``tesseract`` (empty on failure)."""
    if not (shutil.which(_PDFTOPPM) and shutil.which(_TESSERACT)):
        return ""
    try:
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "page"
            render = _run([_PDFTOPPM, "-png", "-r", "200", str(pdf_path), str(prefix)])
            if render.returncode != 0:
                return ""
            texts: list[str] = []
            for png in sorted(Path(td).glob("page*.png")):
                ocr = _run([_TESSERACT, str(png), "stdout"])
                if ocr.returncode == 0:
                    texts.append(ocr.stdout)
            return "\n".join(texts)
    except (OSError, subprocess.SubprocessError):
        return ""


def extract_pdf_text(pdf_path: str | Path) -> tuple[str, str]:
    """Return ``(text, method)`` where method is ``embedded``, ``ocr``, or ``none``.

    Prefers the digital text layer and only falls back to OCR when the PDF has
    little or no embedded text (i.e. it is a scan).
    """
    pdf_path = Path(pdf_path)
    text = _embedded_text(pdf_path)
    if len(text.strip()) >= _EMBEDDED_TEXT_FLOOR:
        return text, "embedded"
    ocr = _ocr_text(pdf_path)
    if ocr.strip():
        return ocr, "ocr"
    if text.strip():
        return text, "embedded"
    return "", "none"


def parse_intake_pairs(text: str) -> dict[str, str]:
    """Lift literal ``Label: value`` lines from extracted text (first label wins)."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        match = _PAIR_RE.match(line)
        if not match:
            continue
        label, value = match.group(1).strip(), match.group(2).strip()
        if label and value and label not in pairs:
            pairs[label] = value
    return pairs


def prefill_intake_from_pdf(
    pdf_path: str | Path,
    *,
    chapter: str = "PA",
    applicant_ref: str = "",
) -> tuple[IntakeRecord, str, str]:
    """Extract, parse, and structure an uploaded intake PDF for human review.

    Returns ``(intake, raw_text, method)``. The intake is a best-effort prefill
    the reviewer corrects against the original PDF; unrecognised lines land in
    ``intake.unmapped`` so nothing is silently dropped or invented.
    """
    text, method = extract_pdf_text(pdf_path)
    intake = structure_intake(
        parse_intake_pairs(text), chapter=chapter, applicant_ref=applicant_ref
    )
    return intake, text, method
