"""SQLite storage layer: schema + JSONL importer (spec v3 §10 item 14)."""

from __future__ import annotations

import json

from risk_engine import database as db


def _exon_row(nre_id: str, *, matched: bool, flags: list[dict]) -> dict:
    return {
        "nre_id": nre_id,
        "provenance": "nre_exoneration",
        "name": "Test Person",
        "state": "Pennsylvania",
        "county": "Allegheny",
        "crime": "Murder",
        "crime_year": 1990,
        "conviction_year": 1991,
        "matched": matched,
        "innocence_project": True,
        "labels": ["discredited_forensic_method"],
        "unmapped_factors": ["False Confession"],
        "predicted": ["discredited_forensic_method"],
        "flags": flags,
    }


def _flag() -> dict:
    return {
        "category": "discredited_forensic_method",
        "basis": "directly_stated",
        "extraction_confidence": 0.9,
        "source_passage": "microscopic hair comparison was used",
        "verification_source": "NAS 2009",
        "descriptors": {"discreditation_tier": "A"},
    }


def test_schema_and_exoneration_import(tmp_path):
    dbfile = tmp_path / "app.db"
    with db.connection(dbfile) as conn:
        n = db.import_exoneration_rows(
            conn, [_exon_row("EX1", matched=True, flags=[_flag(), _flag()])]
        )
    assert n == 1
    with db.connection(dbfile) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exoneration_cases").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM case_flags").fetchone()[0] == 2
        row = conn.execute("SELECT * FROM exoneration_cases WHERE nre_id='EX1'").fetchone()
        assert row["matched"] == 1
        assert json.loads(row["labels"]) == ["discredited_forensic_method"]
        # Normalized flags are queryable by category (the analytics motivation).
        by_cat = conn.execute(
            "SELECT category, COUNT(*) c FROM case_flags GROUP BY category"
        ).fetchall()
        assert dict((r["category"], r["c"]) for r in by_cat) == {
            "discredited_forensic_method": 2
        }


def test_reimport_is_idempotent(tmp_path):
    dbfile = tmp_path / "app.db"
    row = _exon_row("EX1", matched=True, flags=[_flag()])
    with db.connection(dbfile) as conn:
        db.import_exoneration_rows(conn, [row])
        db.import_exoneration_rows(conn, [row])  # re-import same id
    with db.connection(dbfile) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exoneration_cases").fetchone()[0] == 1
        # Flags rewritten, not duplicated.
        assert conn.execute("SELECT COUNT(*) FROM case_flags").fetchone()[0] == 1


def test_case_file_import_and_status(tmp_path):
    dbfile = tmp_path / "app.db"
    cf = {
        "case_id": "CF-abc123",
        "provenance": "submitted_intake",
        "submitted_at": "2026-07-13T00:00:00+00:00",
        "chapter": "PA",
        "applicant_ref": "ref",
        "fields": {"applicant_full_name": "Jane Doe"},
        "unmapped": [],
        "record_status": "ACQUIRING",
        "source_key": "demo_famous",
        "record_searches": [],
        "retrieval_error": "",
        "retrieved_at": "",
        "pdf_stored": False,
        "pdf_original_name": "",
    }
    with db.connection(dbfile) as conn:
        assert db.import_case_file_rows(conn, [cf]) == 1
    with db.connection(dbfile) as conn:
        r = conn.execute("SELECT * FROM case_files WHERE case_id='CF-abc123'").fetchone()
        assert r["record_status"] == "ACQUIRING"
        assert json.loads(r["fields"])["applicant_full_name"] == "Jane Doe"
        assert r["pdf_stored"] == 0


def test_build_db_from_jsonl(tmp_path):
    store = tmp_path / "case_store.jsonl"
    store.write_text(json.dumps(_exon_row("EX9", matched=False, flags=[])) + "\n")
    files = tmp_path / "case_files.jsonl"  # absent-safe: don't create
    counts = db.build_db_from_jsonl(
        db_path=tmp_path / "app.db", store_jsonl=store, case_files_jsonl=files
    )
    assert counts == {"exoneration_cases": 1, "case_files": 0}
