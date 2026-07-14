"""Intake worklist: submitted case files grouped by workflow state (gap-as-action).

The /cases tab leads with an actionable worklist. A gap (NOT_FOUND) or error is
surfaced as work to resolve, never a clean result (README v2 §6.6); linked cases
surface their flags to review. Ordered by state, never scored or ranked (§3.1).
"""

from __future__ import annotations

import pytest

from risk_engine.casefiles import (
    PROVENANCE_SUBMITTED,
    CaseFile,
)
from risk_engine.models import Flag, FlagCategory
from risk_engine.packet import assemble_packet, serialize_packet_flags
from risk_engine.ui.forms import worklist_view


def _cf(case_id: str, status: str, *, flags=None, dispo=None) -> CaseFile:
    serialized = []
    if flags:
        packet = assemble_packet(case_id=case_id, flags=flags)
        serialized = serialize_packet_flags(packet)
        if dispo:  # mark the first flag with a disposition (no longer "open")
            serialized[0]["disposition"] = dispo
    searches = [{"record_type": "opinion", "status": "found_with_flags", "detail": "d"}] if status == "LINKED" else []
    return CaseFile(
        case_id=case_id,
        provenance=PROVENANCE_SUBMITTED,
        submitted_at="2026-01-01T00:00:00+00:00",
        chapter="PA",
        applicant_ref="x",
        fields={"applicant_full_name": case_id},
        record_status=status,
        record_searches=searches,
        flags=serialized,
    )


def test_worklist_groups_by_state():
    forensic = [Flag(category=FlagCategory.DISCREDITED_FORENSIC_METHOD, extraction_confidence=0.9)]
    files = [
        _cf("gap1", "NOT_FOUND"),
        _cf("err1", "ERROR"),
        _cf("acq1", "ACQUIRING"),
        _cf("lnk1", "LINKING"),
        _cf("done1", "LINKED", flags=forensic, dispo="confirmed"),
        _cf("open1", "LINKED", flags=forensic),  # flag still undecided
    ]
    wl = worklist_view(files)
    assert wl["counts"]["needs_attention"] == 2  # gap + error
    assert wl["counts"]["in_progress"] == 2  # acquiring + linking
    assert wl["counts"]["linked"] == 2
    assert wl["counts"]["open_flags"] == 1  # only open1 has an undecided flag
    assert {r["case_id"] for r in wl["needs_attention"]} == {"gap1", "err1"}
    assert any(r["is_gap"] for r in wl["needs_attention"])
    assert any(r["is_error"] for r in wl["needs_attention"])


def test_worklist_empty():
    wl = worklist_view([])
    assert wl["total"] == 0
    assert wl["counts"] == {"needs_attention": 0, "in_progress": 0, "linked": 0, "open_flags": 0}


def _client_with(monkeypatch, files):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.store import CaseStore
    from risk_engine.ui import app as app_module

    class _Mem(app_module.CaseFileStore):
        @classmethod
        def load(cls, path=None):
            return cls(list(files))

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda c: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _Mem)
    return TestClient(app_module.app)


def test_cases_page_shows_gap_as_action(monkeypatch):
    client = _client_with(monkeypatch, [_cf("CF-gap", "NOT_FOUND")])
    resp = client.get("/cases")
    assert resp.status_code == 200
    assert "Needs attention" in resp.text
    assert "Add record text" in resp.text
    assert "/cases/submitted/CF-gap#records" in resp.text


def test_cases_page_shows_review_cta_for_open_flags(monkeypatch):
    forensic = [Flag(category=FlagCategory.DISCREDITED_FORENSIC_METHOD, extraction_confidence=0.9)]
    client = _client_with(monkeypatch, [_cf("CF-open", "LINKED", flags=forensic)])
    resp = client.get("/cases")
    assert resp.status_code == 200
    assert "Records linked" in resp.text
    assert "Review 1 flag(s)" in resp.text
