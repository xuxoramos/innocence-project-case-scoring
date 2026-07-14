"""Tests for the submitted case-file store and its UI routes (spec v3, point 1)."""

from __future__ import annotations

import pytest

from risk_engine.casefiles import (
    PROVENANCE_SUBMITTED,
    RECORD_STATUS_NOT_STARTED,
    CaseFile,
    CaseFileStore,
    case_file_from_intake,
    load_case_files,
    save_case_files,
)
from risk_engine.intake.structuring import structure_intake
from risk_engine.store import CaseStore


def _intake(name: str = "Jane Doe", **fields):
    raw = {"applicant_full_name": name}
    raw.update(fields)
    return structure_intake(raw, chapter="PA", applicant_ref=name.lower().replace(" ", "-"))


def _case_file(name: str = "Jane Doe", **fields) -> CaseFile:
    return case_file_from_intake(_intake(name, **fields))


def test_case_file_from_intake_populates_fields_and_status():
    cf = _case_file(
        "Jane Doe",
        offense_convicted_of="Robbery",
        conviction_jurisdiction="Allegheny County, Pennsylvania",
        date_of_conviction="1994",
    )
    assert cf.provenance == PROVENANCE_SUBMITTED
    assert cf.record_status == RECORD_STATUS_NOT_STARTED
    assert cf.case_id.startswith("CF-")
    assert cf.name == "Jane Doe"
    assert cf.crime == "Robbery"
    assert cf.jurisdiction == "Allegheny County, Pennsylvania"
    assert cf.conviction_year == 1994
    assert cf.record_status_label == "No records retrieved yet"


def test_case_file_conviction_year_missing_is_none():
    cf = _case_file("No Date Person")
    assert cf.conviction_year is None
    assert cf.crime == ""


def test_case_file_roundtrip_and_rebuild_intake(tmp_path):
    cf = _case_file("Jane Doe", offense_convicted_of="Robbery")
    path = tmp_path / "cf.jsonl"
    save_case_files([cf], path)
    loaded = load_case_files(path)
    assert len(loaded) == 1
    assert loaded[0].to_dict() == cf.to_dict()
    # the saved intake can be re-rendered as the schema form it came in on
    intake = loaded[0].to_intake()
    assert intake.get("applicant_full_name").value == "Jane Doe"
    assert intake.get("offense_convicted_of").value == "Robbery"


def test_case_file_store_add_get_list(tmp_path):
    path = tmp_path / "cf.jsonl"
    store = CaseFileStore.load(path)
    assert len(store) == 0
    a = store.add(_case_file("Alice Applicant"), path)
    store.add(_case_file("Bob Applicant"), path)

    reloaded = CaseFileStore.load(path)
    assert len(reloaded) == 2
    assert reloaded.get(a.case_id).name == "Alice Applicant"
    assert reloaded.get("missing") is None
    assert {f.name for f in reloaded.list()} == {"Alice Applicant", "Bob Applicant"}


class _MemCaseFileStore(CaseFileStore):
    """In-memory stand-in so route tests never touch the real store file."""

    _shared: list = []

    @classmethod
    def load(cls, path=None) -> "_MemCaseFileStore":
        return cls(list(cls._shared))

    def add(self, case_file, path=None):
        _MemCaseFileStore._shared.append(case_file)
        return case_file


def _client(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    _MemCaseFileStore._shared = []
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _MemCaseFileStore)
    # Neutralise the async retrieval job so route tests never spawn real threads;
    # the job itself is covered offline in test_casework.py.
    monkeypatch.setattr(app_module, "start_retrieval", lambda *a, **k: None)
    return TestClient(app_module.app)


def test_intake_save_route_persists_and_confirms(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post(
        "/intake/save",
        data={
            "applicant_full_name": "Rosa Parks",
            "offense_convicted_of": "Robbery",
            "_chapter": "PA",
        },
    )
    assert resp.status_code == 200
    assert "Saved to the case list" in resp.text
    assert "Rosa Parks" in resp.text
    assert len(_MemCaseFileStore._shared) == 1
    assert _MemCaseFileStore._shared[0].name == "Rosa Parks"


def test_saved_intake_appears_in_case_list(monkeypatch):
    client = _client(monkeypatch)
    client.post("/intake/save", data={"applicant_full_name": "Rosa Parks", "_chapter": "PA"})

    listing = client.get("/cases")
    assert listing.status_code == 200
    assert "Case worklist" in listing.text
    assert "Rosa Parks" in listing.text
    cid = _MemCaseFileStore._shared[0].case_id
    assert f'href="/cases/submitted/{cid}"' in listing.text


def test_case_file_detail_route_renders_form(monkeypatch):
    client = _client(monkeypatch)
    client.post(
        "/intake/save",
        data={"applicant_full_name": "Rosa Parks", "offense_convicted_of": "Robbery", "_chapter": "PA"},
    )
    cid = _MemCaseFileStore._shared[0].case_id

    detail = client.get(f"/cases/submitted/{cid}")
    assert detail.status_code == 200
    assert "Submitted case file" in detail.text
    assert "Rosa Parks" in detail.text
    assert "Robbery" in detail.text
    assert "Acquiring court records" in detail.text  # retrieval kicked off on save
    assert "not provided" in detail.text  # unfilled schema fields shown honestly


def test_case_file_detail_route_missing_is_404(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/cases/submitted/CF-does-not-exist")
    assert resp.status_code == 404
    assert "Case file not found" in resp.text


def test_intake_save_triggers_retrieval(monkeypatch):
    client = _client(monkeypatch)
    from risk_engine.ui import app as app_module

    calls: list = []
    monkeypatch.setattr(
        app_module,
        "start_retrieval",
        lambda case_id, intake, **kw: calls.append((case_id, kw.get("source_key"))),
    )
    resp = client.post(
        "/intake/save",
        data={"applicant_full_name": "Rosa Parks", "_source": "allegheny_pa", "_chapter": "PA"},
    )
    assert resp.status_code == 200
    saved = _MemCaseFileStore._shared[0]
    # saved immediately at ACQUIRING with the chosen source recorded
    assert saved.record_status == "ACQUIRING"
    assert saved.source_key == "allegheny_pa"
    # and the async job was kicked off for this case with that source
    assert calls == [(saved.case_id, "allegheny_pa")]
    # the confirmation fragment starts polling the live status endpoint
    assert f"/cases/submitted/{saved.case_id}/status" in resp.text


def test_record_status_endpoint_polls_while_in_flight(monkeypatch):
    client = _client(monkeypatch)
    cf = _case_file("Pat Doe")
    cf.record_status = "LINKING"
    _MemCaseFileStore._shared = [cf]

    resp = client.get(f"/cases/submitted/{cf.case_id}/status")
    assert resp.status_code == 200
    assert "Linking court records" in resp.text
    # non-terminal: carries its own poll trigger so htmx keeps checking
    assert f'hx-get="/cases/submitted/{cf.case_id}/status"' in resp.text
    assert "hx-trigger" in resp.text


def test_record_status_endpoint_stops_when_linked(monkeypatch):
    client = _client(monkeypatch)
    cf = _case_file("Pat Doe")
    cf.record_status = "LINKED"
    cf.record_searches = [
        {"record_type": "appellate opinion", "status": "found_with_flags", "detail": "d"},
        {"record_type": "trial court docket", "status": "not_found", "detail": ""},
    ]
    _MemCaseFileStore._shared = [cf]

    resp = client.get(f"/cases/submitted/{cf.case_id}/status")
    assert resp.status_code == 200
    assert "Court records linked" in resp.text
    assert "appellate opinion" in resp.text
    assert "Not found (gap)" in resp.text  # the gap is shown, not hidden
    # terminal: no poll trigger, so htmx stops
    assert "hx-trigger" not in resp.text


def test_record_status_endpoint_missing_is_404(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/cases/submitted/CF-none/status")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()
    assert "hx-trigger" not in resp.text  # a missing id must never poll forever
