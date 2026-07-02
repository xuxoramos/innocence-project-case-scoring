"""Store of submitted intake case files (the live-intake side of the product).

Separate from the exoneration store (:mod:`risk_engine.store`). README v2 requires
that confirmed exonerations and open/submitted cases are **never commingled**, so
submitted intakes get their own JSON Lines file, stamped
``provenance="submitted_intake"``. This is phase 1 of spec v3: persist a
manually-entered intake so it appears in the case list.

A fresh case file has ``record_status="NOT_STARTED"`` and no linked court records
yet — that is an unstarted retrieval, not a clean result (README v2 §6.6). The
async record-retrieval and labeling steps (spec v3 points 2–4) attach to these
files in later phases and drive ``record_status`` forward.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import settings
from .intake.record import IntakeRecord

#: Where submitted case files are persisted by default (JSON Lines).
DEFAULT_CASE_FILE_STORE_PATH: Path = settings.processed_dir / "case_files.jsonl"

#: Provenance stamped on every row: this store is submitted-intake only.
PROVENANCE_SUBMITTED = "submitted_intake"

#: Record-retrieval lifecycle for a submitted case file. Phase 1 only ever sets
#: ``NOT_STARTED``; the async retrieval job (spec v3 point 2) drives the rest.
RECORD_STATUS_NOT_STARTED = "NOT_STARTED"

#: Human-readable label per record status (forward-looking; phase 1 uses the
#: first entry only). Kept honest per §6.6: "not started" and "not found" are
#: states of missing information, never "clean".
RECORD_STATUS_DISPLAY: dict[str, str] = {
    "NOT_STARTED": "No records retrieved yet",
    "ACQUIRING": "Acquiring court records\u2026",
    "LINKING": "Linking court records\u2026",
    "LINKED": "Court records linked",
    "NOT_FOUND": "No matching record found",
}

_YEAR_RE = re.compile(r"(1[89]\d{2}|20\d{2})")


def _extract_year(value: str) -> int | None:
    """Pull a 4-digit year out of a free-text date field, or ``None``."""
    match = _YEAR_RE.search(value or "")
    return int(match.group(1)) if match else None


def _new_case_id() -> str:
    """Opaque, collision-free local handle for a submitted case file."""
    return f"CF-{uuid4().hex[:12]}"


@dataclass
class CaseFile:
    """One submitted intake, persisted so it appears in the case list.

    ``fields`` maps a §5.1 schema key to the structured value; ``unmapped`` keeps
    questionnaire content the structuring layer could not place, so nothing is
    silently lost. Display accessors derive the list-view columns from ``fields``.
    """

    case_id: str
    provenance: str
    submitted_at: str
    chapter: str
    applicant_ref: str
    fields: dict[str, str] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)
    record_status: str = RECORD_STATUS_NOT_STARTED

    @property
    def name(self) -> str:
        return self.fields.get("applicant_full_name") or self.applicant_ref or "(unnamed)"

    @property
    def jurisdiction(self) -> str:
        return self.fields.get("conviction_jurisdiction", "")

    @property
    def crime(self) -> str:
        return self.fields.get("offense_convicted_of", "")

    @property
    def conviction_year(self) -> int | None:
        return _extract_year(self.fields.get("date_of_conviction", ""))

    @property
    def record_status_label(self) -> str:
        return RECORD_STATUS_DISPLAY.get(self.record_status, self.record_status)

    def to_intake(self) -> IntakeRecord:
        """Rebuild the structured intake this case file was saved from."""
        rec = IntakeRecord(applicant_ref=self.applicant_ref, chapter=self.chapter)
        for key, value in self.fields.items():
            rec.set(key, value)
        rec.unmapped = list(self.unmapped)
        return rec

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "CaseFile":
        return cls(**raw)


def case_file_from_intake(intake: IntakeRecord, *, case_id: str | None = None) -> CaseFile:
    """Build a persistable :class:`CaseFile` from a structured intake."""
    return CaseFile(
        case_id=case_id or _new_case_id(),
        provenance=PROVENANCE_SUBMITTED,
        submitted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        chapter=intake.chapter,
        applicant_ref=intake.applicant_ref,
        fields={key: item.value for key, item in intake.fields.items()},
        unmapped=list(intake.unmapped),
    )


def save_case_files(
    files: list[CaseFile],
    path: str | Path = DEFAULT_CASE_FILE_STORE_PATH,
) -> Path:
    """Persist case files as JSON Lines, one per line (atomic write)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for case_file in files:
            fh.write(json.dumps(case_file.to_dict(), sort_keys=True))
            fh.write("\n")
    os.replace(tmp, path)
    return path


def load_case_files(path: str | Path = DEFAULT_CASE_FILE_STORE_PATH) -> list[CaseFile]:
    """Load case files from JSON Lines, or ``[]`` when the file is absent."""
    path = Path(path)
    if not path.exists():
        return []
    files: list[CaseFile] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                files.append(CaseFile.from_dict(json.loads(line)))
    return files


class CaseFileStore:
    """In-memory query layer over the submitted case files (unranked)."""

    def __init__(self, files: list[CaseFile] | None = None):
        self.files = list(files or [])

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CASE_FILE_STORE_PATH) -> "CaseFileStore":
        return cls(load_case_files(path))

    def __len__(self) -> int:
        return len(self.files)

    def get(self, case_id: str) -> CaseFile | None:
        for case_file in self.files:
            if case_file.case_id == case_id:
                return case_file
        return None

    def list(self) -> list[CaseFile]:
        """Case files, newest submission first (no score, no rank)."""
        return sorted(self.files, key=lambda f: f.submitted_at, reverse=True)

    def add(
        self,
        case_file: CaseFile,
        path: str | Path = DEFAULT_CASE_FILE_STORE_PATH,
    ) -> CaseFile:
        """Append a case file and persist the whole store (atomic)."""
        self.files.append(case_file)
        save_case_files(self.files, path)
        return case_file
