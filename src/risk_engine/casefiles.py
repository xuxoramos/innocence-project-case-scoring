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
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import database as _db
from .config import settings
from .database import DEFAULT_DB_PATH
from .intake.record import IntakeRecord

#: Where submitted case files are persisted by default (JSON Lines).
DEFAULT_CASE_FILE_STORE_PATH: Path = settings.processed_dir / "case_files.jsonl"

#: Where the original uploaded intake PDFs are retained, one ``{case_id}.pdf`` per
#: saved case file (spec v3 point 1: the PDF is kept as the verification surface).
DEFAULT_CASE_PDF_DIR: Path = settings.processed_dir / "case_pdfs"

#: Where freshly uploaded PDFs live between upload and save, keyed by an opaque
#: token, until the reviewer saves and they are promoted into the case store.
DEFAULT_INTAKE_STAGING_DIR: Path = settings.processed_dir / "intake_uploads"

#: Provenance stamped on every row: this store is submitted-intake only.
PROVENANCE_SUBMITTED = "submitted_intake"

#: Record-retrieval lifecycle for a submitted case file. A fresh save starts at
#: ``ACQUIRING`` and the background job (spec v3 point 2, :mod:`risk_engine.casework`)
#: drives it through ``LINKING`` to a terminal state. ``NOT_STARTED`` remains for
#: files saved before retrieval was wired up.
RECORD_STATUS_NOT_STARTED = "NOT_STARTED"
RECORD_STATUS_ACQUIRING = "ACQUIRING"
RECORD_STATUS_LINKING = "LINKING"
RECORD_STATUS_LINKED = "LINKED"
RECORD_STATUS_NOT_FOUND = "NOT_FOUND"
RECORD_STATUS_ERROR = "ERROR"

#: Statuses at which the retrieval lifecycle is finished (the UI stops polling).
TERMINAL_RECORD_STATUSES: frozenset[str] = frozenset(
    {RECORD_STATUS_LINKED, RECORD_STATUS_NOT_FOUND, RECORD_STATUS_ERROR, RECORD_STATUS_NOT_STARTED}
)

#: Human-readable label per record status. Kept honest per §6.6: "not found" is a
#: state of missing information, never "clean".
RECORD_STATUS_DISPLAY: dict[str, str] = {
    "NOT_STARTED": "No records retrieved yet",
    "ACQUIRING": "Acquiring court records\u2026",
    "LINKING": "Linking court records\u2026",
    "LINKED": "Court records linked",
    "NOT_FOUND": "No matching record found",
    "ERROR": "Record retrieval failed",
}

#: Human label per persisted record-search status value (mirrors
#: :class:`~risk_engine.packet.RecordSearchStatus`; stored as its ``.value``).
RECORD_SEARCH_STATUS_DISPLAY: dict[str, str] = {
    "found_with_flags": "Found \u2014 has flags",
    "found_no_flags": "Found \u2014 no flags",
    "not_found": "Not found (gap)",
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
    source_key: str = ""
    record_searches: list[dict] = field(default_factory=list)
    retrieval_error: str = ""
    retrieved_at: str = ""
    pdf_stored: bool = False
    pdf_original_name: str = ""

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

    @property
    def record_retrieval_terminal(self) -> bool:
        """True once the retrieval lifecycle has stopped (UI can stop polling)."""
        return self.record_status in TERMINAL_RECORD_STATUSES

    @property
    def record_search_views(self) -> list[dict]:
        """Persisted record searches enriched with a human status label (\u00a76.6).

        A ``not_found`` entry is a searched-but-absent gap, kept distinct from a
        record that came back with no flags \u2014 the two are never conflated.
        """
        views: list[dict] = []
        for rec in self.record_searches:
            status = rec.get("status", "")
            views.append(
                {
                    "record_type": rec.get("record_type", ""),
                    "status": status,
                    "status_label": RECORD_SEARCH_STATUS_DISPLAY.get(status, status),
                    "detail": rec.get("detail", ""),
                    "found": status != "not_found",
                }
            )
        return views

    @property
    def linked_record_count(self) -> int:
        """How many searched record types actually returned a document."""
        return sum(1 for r in self.record_searches if r.get("status") != "not_found")

    @property
    def has_pdf(self) -> bool:
        """Whether the original uploaded intake PDF is retained with this file."""
        return self.pdf_stored

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
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    """Replace the whole submitted-intake store with ``files`` (canonical: SQLite).

    Rewrites the ``case_files`` table and refreshes the git-diffable JSONL export
    beside the database. Kept for bulk/whole-store saves; the request path uses
    the targeted :meth:`CaseFileStore.add` / :func:`update_case_file` instead so
    a background writer never clobbers a concurrent one.
    """
    files = list(files)
    with _STORE_LOCK:
        with _db.connection(db_path) as conn:
            conn.execute("DELETE FROM case_files")
            conn.executemany(_INSERT_SQL, [_case_file_to_row(cf) for cf in files])
        _export_case_files_jsonl(files, db_path=db_path)
    return Path(db_path)


def load_case_files(db_path: str | Path = DEFAULT_DB_PATH) -> list[CaseFile]:
    """Load all submitted case files from the SQLite store."""
    with _db.connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM case_files").fetchall()
    return [_row_to_case_file(r) for r in rows]


# --- SQLite row (de)serialization + JSONL export ------------------------------

#: JSON-encoded columns on the ``case_files`` table.
_JSON_FILE_COLUMNS: tuple[str, ...] = ("fields", "unmapped", "record_searches")

#: Column order for inserts (matches the schema in ``database.py``).
_FILE_COLUMNS: tuple[str, ...] = (
    "case_id", "provenance", "submitted_at", "chapter", "applicant_ref", "fields",
    "unmapped", "record_status", "source_key", "record_searches", "retrieval_error",
    "retrieved_at", "pdf_stored", "pdf_original_name",
)

_INSERT_SQL = (
    "INSERT OR REPLACE INTO case_files ("
    + ", ".join(_FILE_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" for _ in _FILE_COLUMNS)
    + ")"
)

#: Name of the reviewable JSONL export, written beside the database.
_EXPORT_NAME = "case_files.jsonl"


def _case_file_to_row(cf: CaseFile) -> tuple:
    """Positional row for :data:`_INSERT_SQL` (JSON columns encoded, bools -> int)."""
    return (
        cf.case_id,
        cf.provenance,
        cf.submitted_at,
        cf.chapter,
        cf.applicant_ref,
        json.dumps(cf.fields, sort_keys=True),
        json.dumps(list(cf.unmapped)),
        cf.record_status,
        cf.source_key,
        json.dumps(list(cf.record_searches)),
        cf.retrieval_error,
        cf.retrieved_at,
        1 if cf.pdf_stored else 0,
        cf.pdf_original_name,
    )


def _row_to_case_file(row) -> CaseFile:
    """Rebuild a :class:`CaseFile` from a ``case_files`` row."""
    return CaseFile(
        case_id=row["case_id"],
        provenance=row["provenance"],
        submitted_at=row["submitted_at"],
        chapter=row["chapter"],
        applicant_ref=row["applicant_ref"],
        fields=json.loads(row["fields"]),
        unmapped=json.loads(row["unmapped"]),
        record_status=row["record_status"],
        source_key=row["source_key"],
        record_searches=json.loads(row["record_searches"]),
        retrieval_error=row["retrieval_error"],
        retrieved_at=row["retrieved_at"],
        pdf_stored=bool(row["pdf_stored"]),
        pdf_original_name=row["pdf_original_name"],
    )


def _export_jsonl_path(db_path: str | Path) -> Path:
    """Where the reviewable JSONL export lives (beside the database).

    Guards against the degenerate case where the database itself is named like
    the export (e.g. a test fixture), so the export never overwrites the DB.
    """
    p = Path(db_path)
    export = p.with_name(_EXPORT_NAME)
    if export == p:
        export = p.with_name(f"{p.stem}.{_EXPORT_NAME}")
    return export


def _export_case_files_jsonl(files: list[CaseFile], *, db_path: str | Path) -> Path:
    """Write the git-diffable JSONL export of the case files (atomic)."""
    path = _export_jsonl_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for case_file in files:
            fh.write(json.dumps(case_file.to_dict(), sort_keys=True))
            fh.write("\n")
    os.replace(tmp, path)
    return path


def _refresh_export(db_path: str | Path) -> None:
    """Re-emit the JSONL export from the current DB contents."""
    _export_case_files_jsonl(load_case_files(db_path), db_path=db_path)


#: Serialises the load-modify-save cycle so a background retrieval job and the
#: request handlers never clobber each other's writes to the JSON Lines file.
_STORE_LOCK = threading.Lock()

#: Fields :func:`update_case_file` is allowed to mutate (guards against typos
#: silently writing junk attributes onto the dataclass).
_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {"record_status", "source_key", "record_searches", "retrieval_error", "retrieved_at"}
)


def update_case_file(
    case_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    **changes: object,
) -> CaseFile | None:
    """Apply field changes to one persisted case file with a targeted SQL UPDATE.

    The lifecycle transition (the state machine) is a single-row ``UPDATE``, so a
    background retrieval job and a concurrent save never clobber each other.
    Returns the updated file, or ``None`` when no row matches ``case_id``.
    """
    unknown = set(changes) - _UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"cannot update unknown case-file fields: {sorted(unknown)}")
    if not changes:
        return CaseFileStore.load(db_path).get(case_id)
    assignments = ", ".join(f"{field} = ?" for field in changes)
    values = [
        json.dumps(list(value)) if field in _JSON_FILE_COLUMNS else value  # type: ignore[arg-type]
        for field, value in changes.items()
    ]
    with _STORE_LOCK:
        with _db.connection(db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM case_files WHERE case_id = ?", (case_id,)
            ).fetchone()
            if exists is None:
                return None
            conn.execute(
                f"UPDATE case_files SET {assignments} WHERE case_id = ?",
                (*values, case_id),
            )
            row = conn.execute(
                "SELECT * FROM case_files WHERE case_id = ?", (case_id,)
            ).fetchone()
        _refresh_export(db_path)
    return _row_to_case_file(row)


#: Handles are our own opaque ids (``CF-<hex>`` case ids, uuid hex tokens); this
#: allowlist keeps a caller-supplied id from escaping its directory (path traversal).
_SAFE_HANDLE_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")

#: PDF magic bytes — an uploaded file must start with these to be stored.
_PDF_MAGIC = b"%PDF-"


def _safe_handle(handle: str) -> str:
    if not _SAFE_HANDLE_RE.match(handle or ""):
        raise ValueError(f"unsafe file handle: {handle!r}")
    return handle


def looks_like_pdf(data: bytes) -> bool:
    """True if the bytes begin with the PDF magic marker."""
    return data[:5] == _PDF_MAGIC


def case_pdf_path(case_id: str, *, base_dir: str | Path | None = None) -> Path:
    """Path of the retained original PDF for a saved case file."""
    base = Path(base_dir) if base_dir is not None else DEFAULT_CASE_PDF_DIR
    return base / f"{_safe_handle(case_id)}.pdf"


def staged_pdf_path(token: str, *, base_dir: str | Path | None = None) -> Path:
    """Path of an uploaded-but-not-yet-saved PDF, keyed by its upload token."""
    base = Path(base_dir) if base_dir is not None else DEFAULT_INTAKE_STAGING_DIR
    return base / f"{_safe_handle(token)}.pdf"


def _write_bytes(path: Path, data: bytes) -> Path:
    """Atomically write bytes to ``path`` (parent created as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def save_staged_pdf(
    token: str,
    data: bytes,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    """Persist an uploaded PDF to the staging area under ``token``."""
    return _write_bytes(staged_pdf_path(token, base_dir=base_dir), data)


def promote_staged_pdf(
    token: str,
    case_id: str,
    *,
    staging_dir: str | Path | None = None,
    pdf_dir: str | Path | None = None,
) -> bool:
    """Move a staged upload into the case store as ``{case_id}.pdf``.

    Returns ``True`` when a staged file existed and was promoted, ``False`` when
    there was nothing to promote (e.g. no PDF was uploaded for this intake).
    """
    src = staged_pdf_path(token, base_dir=staging_dir)
    if not src.exists():
        return False
    dst = case_pdf_path(case_id, base_dir=pdf_dir)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return True


class CaseFileStore:
    """In-memory query layer over the submitted case files (unranked)."""

    def __init__(self, files: list[CaseFile] | None = None):
        self.files = list(files or [])

    @classmethod
    def load(cls, db_path: str | Path = DEFAULT_DB_PATH) -> "CaseFileStore":
        return cls(load_case_files(db_path))

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
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> CaseFile:
        """Persist one new case file (targeted upsert) and refresh the export."""
        self.files.append(case_file)
        with _STORE_LOCK:
            with _db.connection(db_path) as conn:
                conn.execute(_INSERT_SQL, _case_file_to_row(case_file))
            _refresh_export(db_path)
        return case_file
