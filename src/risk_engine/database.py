"""SQLite storage layer (spec v3 §10, consultant-review item 14 reversal).

As the product leans into intake plus analytics over the body of (simulated)
exoneration cases "sitting" in the IP database, and the intake record lifecycle
is a genuine state machine, the flat JSONL stores are re-backed by a single
SQLite database. This module owns the connection, the schema, and the one-time
importer that loads the existing JSONL stores into the DB.

Design notes:
* **Normalized flags.** The per-element flags live in their own ``case_flags``
  table so analytics (counts by category, predicted-vs-label agreement) are SQL
  ``GROUP BY`` rather than Python loops.
* **JSON columns for small lists.** ``labels`` / ``unmapped_factors`` /
  ``predicted`` / ``record_searches`` / intake ``fields`` are stored as JSON
  text — they are read whole, never aggregated across rows.
* **Reviewable exports kept.** The DB is the canonical, shipped artifact, but the
  stores still export the git-diffable JSONL alongside it (see ``store`` /
  ``casefiles``), so changes remain reviewable.
* Standard library only (``sqlite3``); no new dependency.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

#: Canonical application database. Ships in git (data/processed is force-added).
DEFAULT_DB_PATH: Path = settings.processed_dir / "app.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exoneration_cases (
    nre_id            TEXT PRIMARY KEY,
    provenance        TEXT    NOT NULL DEFAULT '',
    name              TEXT    NOT NULL DEFAULT '',
    state             TEXT    NOT NULL DEFAULT '',
    county            TEXT    NOT NULL DEFAULT '',
    crime             TEXT    NOT NULL DEFAULT '',
    crime_year        INTEGER,
    conviction_year   INTEGER,
    matched           INTEGER NOT NULL DEFAULT 0,
    innocence_project INTEGER NOT NULL DEFAULT 0,
    labels            TEXT    NOT NULL DEFAULT '[]',
    unmapped_factors  TEXT    NOT NULL DEFAULT '[]',
    predicted         TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS case_flags (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nre_id              TEXT    NOT NULL REFERENCES exoneration_cases(nre_id) ON DELETE CASCADE,
    category            TEXT    NOT NULL,
    basis               TEXT    NOT NULL,
    extraction_confidence REAL  NOT NULL DEFAULT 0,
    source_passage      TEXT    NOT NULL DEFAULT '',
    verification_source TEXT,
    descriptors         TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_case_flags_nre      ON case_flags(nre_id);
CREATE INDEX IF NOT EXISTS idx_case_flags_category ON case_flags(category);
CREATE INDEX IF NOT EXISTS idx_exon_state          ON exoneration_cases(state);
CREATE INDEX IF NOT EXISTS idx_exon_matched        ON exoneration_cases(matched);

CREATE TABLE IF NOT EXISTS case_files (
    case_id           TEXT PRIMARY KEY,
    provenance        TEXT    NOT NULL DEFAULT '',
    submitted_at      TEXT    NOT NULL DEFAULT '',
    chapter           TEXT    NOT NULL DEFAULT '',
    applicant_ref     TEXT    NOT NULL DEFAULT '',
    fields            TEXT    NOT NULL DEFAULT '{}',
    unmapped          TEXT    NOT NULL DEFAULT '[]',
    record_status     TEXT    NOT NULL DEFAULT 'NOT_STARTED',
    source_key        TEXT    NOT NULL DEFAULT '',
    record_searches   TEXT    NOT NULL DEFAULT '[]',
    retrieval_error   TEXT    NOT NULL DEFAULT '',
    retrieved_at      TEXT    NOT NULL DEFAULT '',
    pdf_stored        INTEGER NOT NULL DEFAULT 0,
    pdf_original_name TEXT    NOT NULL DEFAULT '',
    flags             TEXT    NOT NULL DEFAULT '[]',
    notes             TEXT    NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_case_files_status ON case_files(record_status);
"""

#: Columns added to ``case_files`` after the table first shipped. Applied as an
#: idempotent ``ALTER TABLE`` so an existing (git-committed) ``app.db`` gains the
#: persisted-flags workflow without a destructive rebuild.
_CASE_FILE_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("flags", "ALTER TABLE case_files ADD COLUMN flags TEXT NOT NULL DEFAULT '[]'"),
    ("notes", "ALTER TABLE case_files ADD COLUMN notes TEXT NOT NULL DEFAULT '[]'"),
)


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the tables and indexes if they do not already exist."""
    conn.executescript(_SCHEMA)
    _migrate_case_files(conn)


def _migrate_case_files(conn: sqlite3.Connection) -> None:
    """Add later ``case_files`` columns to an already-created table (idempotent)."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(case_files)")}
    for column, ddl in _CASE_FILE_MIGRATIONS:
        if column not in have:
            conn.execute(ddl)


@contextmanager
def connection(path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a connection, ensure the schema, commit on success, always close."""
    conn = connect(path)
    try:
        init_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- JSONL -> DB import (one-time migration; also the JSON->DB build step) -----

def _json(value: object, default: str) -> str:
    """Serialize a list/dict column, tolerating an already-JSON string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def import_exoneration_rows(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Insert/replace exoneration rows (with their normalized flags). Returns count."""
    n = 0
    for row in rows:
        nre_id = row["nre_id"]
        conn.execute(
            """
            INSERT OR REPLACE INTO exoneration_cases
              (nre_id, provenance, name, state, county, crime, crime_year,
               conviction_year, matched, innocence_project, labels,
               unmapped_factors, predicted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                nre_id,
                row.get("provenance", ""),
                row.get("name", ""),
                row.get("state", ""),
                row.get("county", ""),
                row.get("crime", ""),
                row.get("crime_year"),
                row.get("conviction_year"),
                1 if row.get("matched") else 0,
                1 if row.get("innocence_project") else 0,
                _json(row.get("labels"), "[]"),
                _json(row.get("unmapped_factors"), "[]"),
                _json(row.get("predicted"), "[]"),
            ),
        )
        # Rewrite this case's flags (idempotent re-import).
        conn.execute("DELETE FROM case_flags WHERE nre_id = ?", (nre_id,))
        for flag in row.get("flags", []):
            conn.execute(
                """
                INSERT INTO case_flags
                  (nre_id, category, basis, extraction_confidence,
                   source_passage, verification_source, descriptors)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    nre_id,
                    flag.get("category", ""),
                    flag.get("basis", ""),
                    flag.get("extraction_confidence", 0.0),
                    flag.get("source_passage", ""),
                    flag.get("verification_source"),
                    _json(flag.get("descriptors"), "{}"),
                ),
            )
        n += 1
    return n


def import_case_file_rows(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Insert/replace submitted-intake case-file rows. Returns count."""
    n = 0
    for row in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO case_files
              (case_id, provenance, submitted_at, chapter, applicant_ref, fields,
               unmapped, record_status, source_key, record_searches,
               retrieval_error, retrieved_at, pdf_stored, pdf_original_name,
               flags, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["case_id"],
                row.get("provenance", ""),
                row.get("submitted_at", ""),
                row.get("chapter", ""),
                row.get("applicant_ref", ""),
                _json(row.get("fields"), "{}"),
                _json(row.get("unmapped"), "[]"),
                row.get("record_status", "NOT_STARTED"),
                row.get("source_key", ""),
                _json(row.get("record_searches"), "[]"),
                row.get("retrieval_error", ""),
                row.get("retrieved_at", ""),
                1 if row.get("pdf_stored") else 0,
                row.get("pdf_original_name", ""),
                _json(row.get("flags"), "[]"),
                _json(row.get("notes"), "[]"),
            ),
        )
        n += 1
    return n


def _read_jsonl(path: str | Path) -> Iterator[dict]:
    """Yield parsed rows from a JSON Lines file, or nothing if it is absent."""
    path = Path(path)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_db_from_jsonl(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    store_jsonl: str | Path | None = None,
    case_files_jsonl: str | Path | None = None,
) -> dict[str, int]:
    """Build/refresh the SQLite DB from the existing JSONL stores.

    Reads the two JSON Lines stores (defaults under ``data/processed``) and loads
    them into ``db_path``. Idempotent: rows are inserted-or-replaced, so it is
    safe to re-run. Returns the row counts imported per store.
    """
    store_jsonl = store_jsonl or (settings.processed_dir / "case_store.jsonl")
    case_files_jsonl = case_files_jsonl or (settings.processed_dir / "case_files.jsonl")
    with connection(db_path) as conn:
        exon = import_exoneration_rows(conn, _read_jsonl(store_jsonl))
        files = import_case_file_rows(conn, _read_jsonl(case_files_jsonl))
    return {"exoneration_cases": exon, "case_files": files}

