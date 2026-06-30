"""Tests for the exoneration -> court-record -> intake labeled-dataset chain."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from risk_engine.acquisition import register_source
from risk_engine.acquisition.base import AcquisitionSource
from risk_engine.dataset import (
    build_labeled_example,
    criteria_from_exoneration,
    intake_from_exoneration,
    match_exoneration,
)
from risk_engine.labels import ExonerationRecord
from risk_engine.models import Case, Document, FlagCategory


class _FakeSource(AcquisitionSource):
    """In-memory source with one named, flag-bearing opinion."""

    jurisdiction = "test_dataset_src"
    display_name = "Test Dataset Source"

    _DATA = [
        (
            "Commonwealth v. Doswell",
            1986,
            "The conviction rested on bite-mark comparison evidence at trial.",
        ),
        ("Commonwealth v. Unrelated", 1990, "An ordinary appeal with nothing notable."),
    ]

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = self._DATA if limit is None else self._DATA[:limit]
        for i, (caption, year, text) in enumerate(rows):
            case = Case(case_id=f"D-{i}", jurisdiction=self.jurisdiction, year=year)
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


def _record(**overrides) -> ExonerationRecord:
    return ExonerationRecord(
        nre_id=overrides.get("nre_id", "NRE-1"),
        name=overrides.get("name", "Thomas Doswell"),
        state=overrides.get("state", "Pennsylvania"),
        county=overrides.get("county", "Allegheny"),
        crime=overrides.get("crime", "Sexual Assault"),
        crime_year=overrides.get("crime_year", 1986),
        conviction_year=overrides.get("conviction_year", 1986),
        factors=overrides.get(
            "factors",
            {"False or Misleading Forensic Evidence", "Official Misconduct"},
        ),
    )


def test_criteria_prefers_conviction_year_then_falls_back():
    crit = criteria_from_exoneration(_record(conviction_year=1986, crime_year=1985))
    assert crit.full_name == "Thomas Doswell"
    assert crit.year == 1986
    fallback = criteria_from_exoneration(_record(conviction_year=None, crime_year=1985))
    assert fallback.year == 1985


def test_intake_backfill_sets_structured_fields_and_provenance():
    intake = intake_from_exoneration(_record())
    assert intake.get("applicant_full_name").value == "Thomas Doswell"
    assert intake.get("offense_convicted_of").value == "Sexual Assault"
    assert intake.get("conviction_jurisdiction").value == "Allegheny County, Pennsylvania"
    assert intake.get("date_of_conviction").value == "1986"
    assert intake.get("claims_actual_innocence").value == "Yes"
    # Narrative prose is never invented from the NRE's structured columns.
    assert intake.get("innocence_rationale") is None
    # Provenance is recorded for human verification.
    assert "NRE:NRE-1" in intake.get("applicant_full_name").source_passage


def test_match_exoneration_finds_named_record():
    match = match_exoneration(_record(), source_key="test_dataset_src")
    assert match is not None
    assert match.is_match
    assert match.case.features["_cl_case_name"] == "Commonwealth v. Doswell"


def test_match_exoneration_returns_none_when_nothing_matches():
    assert match_exoneration(_record(name="Zelda Nobody"), source_key="test_dataset_src") is None


def test_build_labeled_example_links_labels_and_predictions():
    example = build_labeled_example(_record(), source_key="test_dataset_src")
    # NRE ground-truth labels come from the mapped factor columns.
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in example.labels
    # Unmapped failure modes are tracked as known blind spots, not labels.
    assert "Official Misconduct" in example.unmapped_factors
    # The matched opinion was processed; its predicted flags are comparable.
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in example.predicted_categories
    assert example.matched_case is not None


def test_build_labeled_example_offline_skips_matching():
    example = build_labeled_example(_record(), match=False)
    assert example.match is None
    assert example.matched_case is None
    assert example.predicted_categories == set()
    # Back-fill + labels still work with no source access.
    assert example.intake.get("applicant_full_name").value == "Thomas Doswell"
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD in example.labels


def test_download_nre_csv_requires_a_url(monkeypatch):
    from risk_engine.labels import download_nre_csv

    monkeypatch.delenv("NRE_CSV_URL", raising=False)
    with pytest.raises(ValueError, match="No NRE CSV URL"):
        download_nre_csv()
