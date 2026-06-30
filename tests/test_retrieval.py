"""Tests for the intake -> records retrieval flow (README v2 Section 5 + 6.6)."""

from __future__ import annotations

from collections.abc import Iterable

from risk_engine.acquisition import register_source
from risk_engine.acquisition.base import AcquisitionSource
from risk_engine.intake.record import IntakeRecord
from risk_engine.models import Case, Document
from risk_engine.packet import RecordSearchStatus
from risk_engine.retrieval import (
    build_packet_for_intake,
    criteria_from_intake,
    name_score,
    retrieve_for_intake,
    score_candidate,
)


class _FakeSource(AcquisitionSource):
    """In-memory source with named captions, so matching is testable offline."""

    jurisdiction = "test_retrieval_src"
    display_name = "Test Retrieval Source"

    _DATA = [
        (
            "Commonwealth v. Doswell",
            1986,
            "The sole eyewitness identified him at trial; bite-mark comparison was used.",
        ),
        ("Commonwealth v. Unrelated", 1990, "An ordinary appeal with nothing notable."),
    ]

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = self._DATA if limit is None else self._DATA[:limit]
        for i, (caption, year, text) in enumerate(rows):
            case = Case(case_id=f"T-{i}", jurisdiction=self.jurisdiction, year=year)
            case.features["_cl_case_name"] = caption
            case.features["_text"] = text
            yield case

    def fetch(self, case: Case) -> Case:
        if not case.documents:
            case.documents.append(
                Document(
                    doc_id=f"{case.case_id}-OP",
                    case_id=case.case_id,
                    source_uri="https://example/opinions/1/",
                    media_type="text/plain",
                    needs_ocr=False,
                    normalized_text=case.features.get("_text", ""),
                )
            )
        return case


register_source(_FakeSource())


def _intake(**overrides) -> IntakeRecord:
    rec = IntakeRecord(applicant_ref="APP-1")
    rec.set("applicant_full_name", overrides.get("name", "Thomas Doswell"))
    rec.set("date_of_conviction", overrides.get("conviction", "March 1986"))
    rec.set(
        "conviction_jurisdiction",
        overrides.get("jurisdiction", "Allegheny County, Pennsylvania"),
    )
    return rec


def test_name_score_matches_surname_in_caption():
    assert name_score("Thomas Doswell", "Commonwealth v. Doswell") >= 0.8


def test_name_score_rejects_unrelated_caption():
    assert name_score("Thomas Doswell", "Commonwealth v. Unrelated") < 0.6


def test_name_score_empty_is_zero():
    assert name_score("", "Commonwealth v. Doswell") == 0.0


def test_criteria_pulls_name_and_year():
    criteria = criteria_from_intake(_intake())
    assert criteria.full_name == "Thomas Doswell"
    assert criteria.year == 1986


def test_score_candidate_matches_with_corroboration():
    case = next(_FakeSource().discover(limit=1))  # the Doswell case
    match = score_candidate(criteria_from_intake(_intake()), case)
    assert match.is_match
    assert match.year_consistent
    assert match.confidence > match.name_score  # a consistent year nudged it up


def test_retrieve_matches_only_the_right_case_and_flags_it():
    result = retrieve_for_intake(_intake(), source_key="test_retrieval_src")
    assert result.candidates_considered == 2
    assert [m.case.case_id for m in result.matches] == ["T-0"]
    # The matched opinion's text produces witness-ID and forensic flags.
    categories = {f.category.value for f in result.flags}
    assert "witness_id_circumstance" in categories
    assert "discredited_forensic_method" in categories


def test_found_and_not_found_states_are_distinct():
    result = retrieve_for_intake(_intake(), source_key="test_retrieval_src")
    statuses = {r.record_type: r.status for r in result.record_searches}
    # The appellate opinion came back and carried flags.
    assert statuses["appellate opinion"] is RecordSearchStatus.FOUND_WITH_FLAGS
    # Record types we cannot retrieve are honest gaps, never "clean".
    assert statuses["trial court docket"] is RecordSearchStatus.NOT_FOUND
    assert statuses["post-conviction filings"] is RecordSearchStatus.NOT_FOUND


def test_no_match_yields_all_not_found_and_no_flags():
    result = retrieve_for_intake(
        _intake(name="Someone Notinthere"), source_key="test_retrieval_src"
    )
    assert result.matches == []
    assert result.flags == []
    assert all(
        r.status is RecordSearchStatus.NOT_FOUND for r in result.record_searches
    )


def test_build_packet_for_intake_is_end_to_end():
    packet = build_packet_for_intake(_intake(), source_key="test_retrieval_src")
    assert packet.case_id == "APP-1"
    assert packet.intake is not None
    assert packet.has_flags
    assert packet.records_not_found  # the unreachable record types
    rendered = packet.render_text()
    assert "CASE PACKET: APP-1" in rendered
    assert "not_found" in rendered
