"""Persisted case-file flags + reviewer disposition (usable-system spine).

Flags produced when a record is linked are persisted on the case file so a
reviewer can disposition each one. Every assertion here guards the governance
line: flags stay per-element, a disposition is a human judgement, and nothing is
ever combined into a case-level score (README v2 §3.1, §6.6).
"""

from __future__ import annotations

import pytest

from risk_engine.casefiles import (
    DISPOSITION_CONFIRMED,
    PROVENANCE_SUBMITTED,
    RECORD_STATUS_LINKED,
    CaseFile,
    load_case_files,
    save_case_files,
    update_case_file,
    update_flag_disposition,
)
from risk_engine.models import Flag, FlagBasis, FlagCategory
from risk_engine.packet import assemble_packet, serialize_packet_flags


def _seed_linked_case(path, *, case_id: str = "CF-flagtest") -> str:
    """Persist one LINKED case file carrying a single forensic flag; return flag id."""
    cf = CaseFile(
        case_id=case_id,
        provenance=PROVENANCE_SUBMITTED,
        submitted_at="2026-01-01T00:00:00+00:00",
        chapter="PA",
        applicant_ref="x",
        fields={"applicant_full_name": "Test Applicant"},
    )
    save_case_files([cf], path)
    flag = Flag(
        category=FlagCategory.DISCREDITED_FORENSIC_METHOD,
        basis=FlagBasis.DIRECTLY_STATED,
        extraction_confidence=0.92,
        source_passage="microscopic hair comparison testimony",
        verification_source="NAS 2009",
    )
    packet = assemble_packet(case_id=case_id, flags=[flag])
    serialized = serialize_packet_flags(packet)
    update_case_file(
        case_id,
        db_path=path,
        record_status=RECORD_STATUS_LINKED,
        flags=serialized,
        notes=["Trial defense noted: self-defense."],
    )
    return serialized[0]["id"]


def test_serialize_packet_flags_ids_and_undecided():
    flags = [
        Flag(category=FlagCategory.DISCREDITED_FORENSIC_METHOD, extraction_confidence=0.9),
        Flag(category=FlagCategory.WITNESS_ID_CIRCUMSTANCE, extraction_confidence=0.7),
    ]
    packet = assemble_packet(case_id="CF-x", flags=flags)
    out = serialize_packet_flags(packet)
    assert len(out) == 2
    assert len({f["id"] for f in out}) == 2  # stable, unique ids
    assert all(f["disposition"] == "undecided" for f in out)
    # No aggregate/score field is ever emitted — flags stay per-element.
    assert all("score" not in f and "rank" not in f for f in out)


def test_flags_and_notes_persist_roundtrip(tmp_path):
    path = tmp_path / "cf.jsonl"
    _seed_linked_case(path)
    loaded = load_case_files(path)[0]
    assert len(loaded.flags) == 1
    assert loaded.flags[0]["category"] == "discredited_forensic_method"
    assert loaded.flags[0]["verification_source"] == "NAS 2009"
    assert loaded.flags[0]["disposition"] == "undecided"
    assert loaded.notes == ["Trial defense noted: self-defense."]


def test_update_flag_disposition_sets_and_stamps(tmp_path):
    path = tmp_path / "cf.jsonl"
    flag_id = _seed_linked_case(path)
    cf = update_flag_disposition(
        "CF-flagtest", flag_id, disposition=DISPOSITION_CONFIRMED, note="hair testimony", db_path=path
    )
    assert cf is not None
    flag = cf.flags[0]
    assert flag["disposition"] == "confirmed"
    assert flag["disposition_note"] == "hair testimony"
    assert flag["disposition_at"]  # timestamp stamped
    # persisted, not just in-memory
    assert load_case_files(path)[0].flags[0]["disposition"] == "confirmed"


def test_update_flag_disposition_unknown_ids_return_none(tmp_path):
    path = tmp_path / "cf.jsonl"
    flag_id = _seed_linked_case(path)
    assert update_flag_disposition("CF-nope", flag_id, disposition=DISPOSITION_CONFIRMED, db_path=path) is None
    assert update_flag_disposition("CF-flagtest", "badid", disposition=DISPOSITION_CONFIRMED, db_path=path) is None


def test_update_flag_disposition_rejects_unknown_value(tmp_path):
    path = tmp_path / "cf.jsonl"
    flag_id = _seed_linked_case(path)
    with pytest.raises(ValueError):
        update_flag_disposition("CF-flagtest", flag_id, disposition="bogus", db_path=path)


# --- route ------------------------------------------------------------------


def _client_with_tmp_db(monkeypatch, path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine import casefiles
    from risk_engine.ui import app as app_module

    real = casefiles.update_flag_disposition
    monkeypatch.setattr(
        app_module,
        "update_flag_disposition",
        lambda cid, fid, **kw: real(
            cid, fid, db_path=path, **{k: v for k, v in kw.items() if k != "db_path"}
        ),
    )
    return TestClient(app_module.app)


def test_disposition_route_updates_and_renders_fragment(monkeypatch, tmp_path):
    path = tmp_path / "cf.jsonl"
    flag_id = _seed_linked_case(path, case_id="CF-route1")
    client = _client_with_tmp_db(monkeypatch, path)
    resp = client.post(
        f"/cases/submitted/CF-route1/flags/{flag_id}/disposition",
        data={"disposition": "confirmed"},
    )
    assert resp.status_code == 200
    assert "Confirmed in record" in resp.text
    assert f'id="flag-{flag_id}"' in resp.text


def test_disposition_route_rejects_bad_value(monkeypatch, tmp_path):
    path = tmp_path / "cf.jsonl"
    flag_id = _seed_linked_case(path, case_id="CF-route2")
    client = _client_with_tmp_db(monkeypatch, path)
    resp = client.post(
        f"/cases/submitted/CF-route2/flags/{flag_id}/disposition",
        data={"disposition": "sounds_guilty"},
    )
    assert resp.status_code == 400


def test_disposition_route_unknown_case_is_404(monkeypatch, tmp_path):
    path = tmp_path / "cf.jsonl"
    _seed_linked_case(path, case_id="CF-route3")
    client = _client_with_tmp_db(monkeypatch, path)
    resp = client.post(
        "/cases/submitted/CF-does-not-exist/flags/whatever/disposition",
        data={"disposition": "confirmed"},
    )
    assert resp.status_code == 404


def test_detail_page_renders_flags_and_disposition_controls(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.store import CaseStore
    from risk_engine.ui import app as app_module

    cf = CaseFile(
        case_id="CF-render1",
        provenance=PROVENANCE_SUBMITTED,
        submitted_at="2026-01-01T00:00:00+00:00",
        chapter="PA",
        applicant_ref="x",
        fields={"applicant_full_name": "Render Test"},
        record_status=RECORD_STATUS_LINKED,
        record_searches=[{"record_type": "opinion", "status": "found_with_flags", "detail": "op-1"}],
        flags=serialize_packet_flags(
            assemble_packet(
                case_id="CF-render1",
                flags=[
                    Flag(
                        category=FlagCategory.DISCREDITED_FORENSIC_METHOD,
                        extraction_confidence=0.9,
                        source_passage="microscopic hair comparison",
                        verification_source="NAS 2009",
                    )
                ],
            )
        ),
    )

    class _Mem(app_module.CaseFileStore):
        @classmethod
        def load(cls, path=None):
            return cls([cf])

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda c: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _Mem)
    client = TestClient(app_module.app)
    resp = client.get("/cases/submitted/CF-render1")
    assert resp.status_code == 200
    assert "Flagged elements (1)" in resp.text
    assert "microscopic hair comparison" in resp.text
    assert 'value="confirmed"' in resp.text  # disposition controls present
    assert "Needs review" in resp.text  # default disposition label


def test_print_packet_renders_work_product(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.store import CaseStore
    from risk_engine.ui import app as app_module

    cf = CaseFile(
        case_id="CF-print1",
        provenance=PROVENANCE_SUBMITTED,
        submitted_at="2026-01-01T00:00:00+00:00",
        chapter="PA",
        applicant_ref="x",
        fields={"applicant_full_name": "Print Test"},
        record_status=RECORD_STATUS_LINKED,
        record_searches=[{"record_type": "opinion", "status": "found_with_flags", "detail": "op-1"}],
        flags=serialize_packet_flags(
            assemble_packet(
                case_id="CF-print1",
                flags=[
                    Flag(
                        category=FlagCategory.DISCREDITED_FORENSIC_METHOD,
                        extraction_confidence=0.9,
                        source_passage="bite-mark comparison",
                        verification_source="NAS 2009",
                    )
                ],
            )
        ),
    )

    class _Mem(app_module.CaseFileStore):
        @classmethod
        def load(cls, path=None):
            return cls([cf])

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda c: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _Mem)
    client = TestClient(app_module.app)
    resp = client.get("/cases/submitted/CF-print1/print")
    assert resp.status_code == 200
    # A printable work product with flags, disposition, and the standing scope note.
    assert "Print / Save as PDF" in resp.text
    assert "bite-mark comparison" in resp.text
    assert "Reviewer disposition" in resp.text
    assert "no case-level score" in resp.text.lower()


def test_print_packet_missing_case_is_404(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.store import CaseStore
    from risk_engine.ui import app as app_module

    class _Empty(app_module.CaseFileStore):
        @classmethod
        def load(cls, path=None):
            return cls([])

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda c: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _Empty)
    client = TestClient(app_module.app)
    assert client.get("/cases/submitted/CF-nope/print").status_code == 404


