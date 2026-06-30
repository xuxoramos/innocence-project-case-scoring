"""Tests for the web-UI helpers and routes.

The pure helpers in ``risk_engine.ui.forms`` are tested directly. The FastAPI
routes are smoke-tested with Starlette's ``TestClient`` when available, against
the offline ``allegheny_pa`` fixture so no network or token is needed.
"""

from __future__ import annotations

import pytest

from risk_engine.intake.structuring import structure_intake
from risk_engine.retrieval import build_packet_for_intake
from risk_engine.ui.forms import (
    form_field_groups,
    packet_view,
    parse_intake_form,
)


def test_form_field_groups_are_grouped_and_nonempty():
    groups = form_field_groups()
    assert groups, "expected near-universal fields grouped by category"
    # Every group has a label and at least one field with a schema key + label.
    for g in groups:
        assert g["label"]
        assert g["fields"]
        for f in g["fields"]:
            assert f["key"] and f["label"]
            assert isinstance(f["multiline"], bool)


def test_parse_intake_form_splits_meta_and_drops_blanks():
    raw, meta = parse_intake_form(
        {
            "_source": "allegheny_pa",
            "_applicant_ref": "intake-1",
            "applicant_full_name": "  Jane Roe  ",
            "offense_convicted_of": "",
            "date_of_conviction": "1994",
        }
    )
    assert meta == {"_source": "allegheny_pa", "_applicant_ref": "intake-1"}
    assert raw == {"applicant_full_name": "Jane Roe", "date_of_conviction": "1994"}
    assert "offense_convicted_of" not in raw  # blank dropped


def test_packet_view_shape_and_record_states():
    intake = structure_intake(
        {"applicant_full_name": "Jane Roe", "date_of_conviction": "1994"},
        applicant_ref="intake-1",
    )
    packet = build_packet_for_intake(intake, source_key="allegheny_pa")
    view = packet_view(packet)

    assert view["case_id"] == "intake-1"
    assert view["scope_statement"]
    assert isinstance(view["total_flags"], int)
    assert isinstance(view["has_flags"], bool)
    # Offline fixture has no caption matches -> every expected record is a gap.
    assert view["records"], "expected record-search rows"
    assert all(r["status_class"] == "not-found" for r in view["records"])
    assert any("Jane Roe" == f["value"] for g in view["intake_groups"] for f in g["fields"])


def test_app_routes_smoke():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui.app import app

    client = TestClient(app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Flag elements" in home.text

    resp = client.post(
        "/flag",
        data={
            "_source": "allegheny_pa",
            "_applicant_ref": "intake-9",
            "applicant_full_name": "Jane Roe",
            "date_of_conviction": "1994",
        },
    )
    assert resp.status_code == 200
    assert "intake-9" in resp.text
    assert "Record searches" in resp.text
