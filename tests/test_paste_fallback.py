"""Manual-paste fallback + minimum-viable-text threshold (spec v3 items 4 & 5)."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from risk_engine.acquisition import register_source
from risk_engine.acquisition.base import AcquisitionSource
from risk_engine.intake.record import IntakeRecord
from risk_engine.models import Case, Document, FlagCategory
from risk_engine.retrieval import (
    build_packet_for_intake,
    packet_from_pasted_text,
    retrieve_for_intake,
)

_SHORT_OPINION = "Commonwealth v. Doe. Bite-mark comparison testimony was admitted at trial."


class _ThinSource(AcquisitionSource):
    """A matchable source whose opinion text is short (< threshold)."""

    jurisdiction = "thin_text_src"
    display_name = "Thin Text Source"

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        case = Case(case_id="TT-1", jurisdiction=self.jurisdiction, year=1990)
        case.features["_cl_case_name"] = "Commonwealth v. Doe"
        yield case

    def fetch(self, case: Case) -> Case:
        if not case.documents:
            case.documents.append(
                Document(
                    doc_id="TT-1-OP",
                    case_id="TT-1",
                    source_uri="https://example/opinions/1/",
                    media_type="text/plain",
                    needs_ocr=False,
                    normalized_text=_SHORT_OPINION,
                )
            )
        return case


register_source(_ThinSource())


def _intake(name: str = "John Doe") -> IntakeRecord:
    rec = IntakeRecord(applicant_ref="APP")
    rec.set("applicant_full_name", name)
    rec.set("date_of_conviction", "1990")
    return rec


def test_threshold_drops_thin_record_as_gap():
    # With a 1000-char floor, the short opinion is too thin to flag -> gap.
    result = retrieve_for_intake(_intake(), source_key="thin_text_src", min_text_chars=1000)
    assert result.flags == []
    assert all(r.status.value == "not_found" for r in result.record_searches)


def test_no_threshold_still_flags_short_record():
    # Default (no threshold) keeps the existing behaviour: the short record flags.
    result = retrieve_for_intake(_intake(), source_key="thin_text_src", min_text_chars=0)
    cats = {f.category for f in result.flags}
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in cats


def test_build_packet_passes_threshold_through():
    packet = build_packet_for_intake(
        _intake(), source_key="thin_text_src", min_text_chars=1000
    )
    assert packet.total_flags == 0
    assert packet.records_not_found  # honest gap, not clean


def test_pasted_text_is_flagged():
    text = (
        "In this appeal the court considered forensic testimony. A forensic "
        "odontologist offered bite-mark comparison testimony identifying the "
        "defendant as the source of the wound. " + ("padding sentence. " * 60)
    )
    packet = packet_from_pasted_text(_intake(), text, case_id="CF-x")
    forensic = [
        f
        for g in packet.flag_groups
        if g.category is FlagCategory.DISCREDITED_FORENSIC_METHOD
        for f in g.flags
    ]
    assert forensic
    # The pasted text becomes one found record, kept distinct from a gap (§6.6).
    assert any(r.record_type == "pasted appellate text" for r in packet.records)


# --- route -----------------------------------------------------------------


class _MemCaseFileStore:
    _shared: list = []

    def __init__(self, files=None):
        self.files = list(files if files is not None else _MemCaseFileStore._shared)

    @classmethod
    def load(cls, db_path=None):
        return cls(list(cls._shared))

    def get(self, case_id):
        return next((f for f in self.files if f.case_id == case_id), None)


def _client(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.casefiles import case_file_from_intake
    from risk_engine.ui import app as app_module

    case_file = case_file_from_intake(_intake(), case_id="CF-paste1")
    _MemCaseFileStore._shared = [case_file]
    monkeypatch.setattr(app_module, "CaseFileStore", _MemCaseFileStore)
    calls: list[dict] = []
    monkeypatch.setattr(
        app_module, "update_case_file", lambda cid, **kw: calls.append({"cid": cid, **kw})
    )
    return TestClient(app_module.app), calls


def test_paste_route_rejects_short_text(monkeypatch):
    client, calls = _client(monkeypatch)
    resp = client.post("/cases/submitted/CF-paste1/paste-text", data={"text": "too short"})
    assert resp.status_code == 200
    assert "too short" in resp.text
    assert calls == []  # nothing persisted for a rejected paste


def test_paste_route_flags_and_links(monkeypatch):
    client, calls = _client(monkeypatch)
    text = (
        "The State relied on bite-mark comparison testimony from a forensic "
        "odontologist. " + ("procedural history sentence. " * 60)
    )
    resp = client.post("/cases/submitted/CF-paste1/paste-text", data={"text": text})
    assert resp.status_code == 200
    assert "Discredited forensic method" in resp.text or "discredited" in resp.text.lower()
    # The case file was marked linked via a manual-paste record.
    assert calls and calls[0]["record_status"] == "LINKED"
    assert calls[0]["source_key"] == "manual_paste"


def test_paste_route_404_for_unknown_case(monkeypatch):
    client, _ = _client(monkeypatch)
    resp = client.post("/cases/submitted/CF-nope/paste-text", data={"text": "x" * 1200})
    assert resp.status_code == 404
