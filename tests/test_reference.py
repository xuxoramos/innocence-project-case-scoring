"""Aggregate reference context (spec v3 §10 reference library, item 3 family).

For a flag category, the UI surfaces how many confirmed exonerations in the
reference set carried that NRE contributing factor. This is a population
frequency, never a per-case prediction and never a score (README v2 §3.1, §3.2).
"""

from __future__ import annotations

import pytest

from risk_engine import reference
from risk_engine.casefiles import PROVENANCE_SUBMITTED, RECORD_STATUS_LINKED, CaseFile
from risk_engine.models import Flag, FlagCategory
from risk_engine.packet import assemble_packet, serialize_packet_flags
from risk_engine.store import CaseStore, StoredCase
from risk_engine.ui.forms import stored_flag_view


def _store():
    def _c(nre_id, state, labels):
        return StoredCase(
            provenance="nre", nre_id=nre_id, name=nre_id, state=state, county="",
            crime="", crime_year=None, conviction_year=None, matched=False, labels=labels,
        )

    return CaseStore(
        [
            _c("A", "PA", ["discredited_forensic_method", "witness_id_circumstance"]),
            _c("B", "PA", ["discredited_forensic_method"]),
            _c("C", "TX", []),
        ]
    )


def test_category_reference_counts_labels(monkeypatch):
    monkeypatch.setattr(reference.CaseStore, "load", classmethod(lambda cls: _store()))
    reference.reset_cache()
    ref = reference.category_reference()
    assert ref["discredited_forensic_method"] == {"count": 2, "total": 3}
    assert ref["witness_id_circumstance"] == {"count": 1, "total": 3}
    # A category no exoneration carried is simply absent from the map.
    assert "police_misconduct" not in ref
    reference.reset_cache()


def test_stored_flag_view_attaches_reference():
    ref = {"discredited_forensic_method": {"count": 812, "total": 4311}}
    v = stored_flag_view({"category": "discredited_forensic_method"}, ref)
    assert v["reference"] == {"count": 812, "total": 4311}


def test_stored_flag_view_no_reference_is_none():
    assert stored_flag_view({"category": "discredited_forensic_method"})["reference"] is None
    # A category with zero support yields no context (not a misleading "0 of N").
    ref = {"discredited_forensic_method": {"count": 0, "total": 4311}}
    assert stored_flag_view({"category": "discredited_forensic_method"}, ref)["reference"] is None


def test_detail_page_shows_population_context(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    cf = CaseFile(
        case_id="CF-ref1",
        provenance=PROVENANCE_SUBMITTED,
        submitted_at="2026-01-01T00:00:00+00:00",
        chapter="PA",
        applicant_ref="x",
        fields={"applicant_full_name": "Ref Test"},
        record_status=RECORD_STATUS_LINKED,
        record_searches=[{"record_type": "opinion", "status": "found_with_flags", "detail": "d"}],
        flags=serialize_packet_flags(
            assemble_packet(
                case_id="CF-ref1",
                flags=[Flag(category=FlagCategory.DISCREDITED_FORENSIC_METHOD, extraction_confidence=0.9)],
            )
        ),
    )

    class _Mem(app_module.CaseFileStore):
        @classmethod
        def load(cls, path=None):
            return cls([cf])

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda c: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _Mem)
    monkeypatch.setattr(
        app_module,
        "category_reference",
        lambda: {"discredited_forensic_method": {"count": 812, "total": 4311}},
    )
    client = TestClient(app_module.app)
    resp = client.get("/cases/submitted/CF-ref1")
    assert resp.status_code == 200
    assert "812" in resp.text
    assert "of 4311 confirmed exonerations" in resp.text
    assert "not a prediction about this case" in resp.text
