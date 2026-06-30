"""Tests for the CourtListener acquisition source (no network calls)."""

from __future__ import annotations

from risk_engine.acquisition import CourtListenerSource, get_source, list_sources


def test_courtlistener_registered():
    assert "pa_appellate_cl" in list_sources()
    assert isinstance(get_source("pa_appellate_cl"), CourtListenerSource)


def test_result_to_case_parses_metadata():
    src = CourtListenerSource("pa_appellate_cl", "PA appellate")
    case = src._result_to_case(
        {
            "cluster_id": 12345,
            "caseName": "Commonwealth v. Doe",
            "dateFiled": "1994-06-30",
            "docketNumber": "123 WDA 1994",
            "court": "pasuperct",
            "opinions": [{"id": 999}, {"id": 1000}],
        }
    )
    assert case is not None
    assert case.case_id == "CL-12345"
    assert case.year == 1994
    assert case.features["_cl_opinion_ids"] == [999, 1000]
    assert case.features["_cl_case_name"] == "Commonwealth v. Doe"


def test_result_to_case_handles_missing_date():
    src = CourtListenerSource("pa_appellate_cl", "PA appellate")
    case = src._result_to_case({"cluster_id": 1, "opinions": []})
    assert case is not None and case.year is None


def test_opinion_text_prefers_plain_text():
    assert CourtListenerSource._opinion_text({"plain_text": "hi", "html": "<p>x</p>"}) == "hi"
    assert CourtListenerSource._opinion_text({"html": "<p>x</p>"}) == "<p>x</p>"
    assert CourtListenerSource._opinion_text({}) == ""


def test_fetch_is_noop_without_opinion_ids():
    src = CourtListenerSource("pa_appellate_cl", "PA appellate")
    case = src._result_to_case({"cluster_id": 7, "opinions": []})
    # No opinion ids -> fetch must not attempt any network I/O.
    assert src.fetch(case).documents == []
