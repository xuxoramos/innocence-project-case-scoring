"""Demo-only 'demo_famous' source: real, famous exonerations with real records.

These are demonstration fixtures built from verbatim, public-domain CourtListener
opinions for confirmed exonerations. Each fires the flag its real record earns,
and each ships a docket alongside the opinion while leaving post-conviction
filings as an honest gap (README v2 §6.6). Demo-only; never training/label data.
"""

from __future__ import annotations

from pathlib import Path

from risk_engine.acquisition import get_source, list_sources
from risk_engine.intake.structuring import structure_intake
from risk_engine.models import FlagCategory
from risk_engine.packet import RecordSearchStatus
from risk_engine.retrieval import build_packet_for_intake

_OPINIONS = Path(__file__).resolve().parents[1] / "data" / "demo" / "famous"


def test_source_registered():
    assert "demo_famous" in list_sources()


def test_opinion_fixtures_present():
    for name in ("harward_opinion.txt", "huffington_opinion.txt", "chmiel_opinion.txt"):
        p = _OPINIONS / name
        assert p.exists(), f"missing fixture {name}"
        assert len(p.read_text()) > 1000


def test_discover_and_fetch_attach_opinion_and_docket():
    source = get_source("demo_famous")
    cases = list(source.discover())
    assert len(cases) == 3
    fetched = source.fetch(cases[0])
    rtypes = {d.metadata.get("record_type") for d in fetched.documents}
    assert rtypes == {"appellate opinion", "trial court docket"}


def _intake(name: str, year: str, offense: str = "First-degree murder"):
    return structure_intake(
        {"applicant_full_name": name, "date_of_conviction": year, "offense_convicted_of": offense},
        chapter="PA",
        applicant_ref=name.lower().replace(" ", "-"),
    )


def test_harward_fires_bite_mark_forensic_flag():
    packet = build_packet_for_intake(
        _intake("Keith Harward", "1986"), source_key="demo_famous", case_id="CF-h"
    )
    cats = {g.category for g in packet.flag_groups}
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in cats


def test_huffington_fires_hair_and_misconduct():
    packet = build_packet_for_intake(
        _intake("John Norman Huffington", "1981"), source_key="demo_famous", case_id="CF-u"
    )
    cats = {g.category for g in packet.flag_groups}
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in cats
    assert FlagCategory.PROSECUTOR_MISCONDUCT in cats


def test_chmiel_fires_hair_forensic_flag():
    packet = build_packet_for_intake(
        _intake("David Chmiel", "1983"), source_key="demo_famous", case_id="CF-c"
    )
    cats = {g.category for g in packet.flag_groups}
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in cats


def test_docket_found_and_post_conviction_is_a_gap():
    packet = build_packet_for_intake(
        _intake("Keith Harward", "1986"), source_key="demo_famous", case_id="CF-h2"
    )
    by_type = {r.record_type: r.status for r in packet.records}
    # both the opinion and the docket were retrieved...
    assert by_type.get("appellate opinion") in {
        RecordSearchStatus.FOUND_WITH_FLAGS,
        RecordSearchStatus.FOUND_NO_FLAGS,
    }
    assert by_type.get("trial court docket") in {
        RecordSearchStatus.FOUND_WITH_FLAGS,
        RecordSearchStatus.FOUND_NO_FLAGS,
    }
    # ...but the post-conviction filings are an honest gap, not a clean result.
    assert by_type.get("post-conviction filings") is RecordSearchStatus.NOT_FOUND


def test_unknown_applicant_is_a_gap():
    packet = build_packet_for_intake(
        _intake("Bruce Banner", "1990"), source_key="demo_famous", case_id="CF-gap"
    )
    assert packet.total_flags == 0
    assert all(r.status is RecordSearchStatus.NOT_FOUND for r in packet.records)
