"""Tests for the common intake schema and structured intake record."""

from __future__ import annotations

import pytest

from risk_engine.intake import (
    CHAPTER_SOURCES,
    COMMON_INTAKE_SCHEMA,
    ELIGIBILITY_GATES,
    IntakeCategory,
    IntakeRecord,
    fields_for,
    near_universal_fields,
)


def test_every_field_has_known_source_chapters():
    valid = set(CHAPTER_SOURCES)
    for spec in COMMON_INTAKE_SCHEMA:
        assert spec.sources, f"{spec.key} has no source chapter"
        assert set(spec.sources) <= valid, f"{spec.key} cites unknown chapter"


def test_schema_keys_are_unique():
    keys = [s.key for s in COMMON_INTAKE_SCHEMA]
    assert len(keys) == len(set(keys))


def test_all_eight_readme_categories_present():
    covered = {s.category for s in COMMON_INTAKE_SCHEMA}
    # The eight named in README 5.1 must all have at least one field.
    for category in [
        IntakeCategory.PERSONAL_BACKGROUND,
        IntakeCategory.CONVICTION_DETAILS,
        IntakeCategory.CLAIM_OF_INNOCENCE,
        IntakeCategory.INVESTIGATION_HISTORY,
        IntakeCategory.TRIAL_RECORD,
        IntakeCategory.POST_CONVICTION_HISTORY,
        IntakeCategory.EVIDENCE_AVAILABILITY,
        IntakeCategory.MATERIALS_ON_HAND,
    ]:
        assert category in covered, f"{category} has no fields"


def test_actual_innocence_is_near_universal():
    spec = next(s for s in COMMON_INTAKE_SCHEMA if s.key == "claims_actual_innocence")
    assert spec.is_near_universal
    assert set(spec.sources) == {"PA", "IP", "EP", "TX", "MIP"}


def test_dna_evidence_is_chapter_specific_to_national_ip():
    spec = next(s for s in COMMON_INTAKE_SCHEMA if s.key == "biological_dna_evidence_exists")
    assert not spec.is_near_universal
    assert spec.sources == ("IP",)


def test_fields_for_returns_only_that_category():
    convict = fields_for(IntakeCategory.CONVICTION_DETAILS)
    assert convict
    assert all(s.category is IntakeCategory.CONVICTION_DETAILS for s in convict)


def test_eligibility_gates_include_universal_innocence_gate():
    gate = next(g for g in ELIGIBILITY_GATES if g.key == "actual_innocence_claim")
    assert set(gate.sources) == {"PA", "IP", "EP", "TX", "MIP"}


def test_record_set_rejects_unknown_key():
    rec = IntakeRecord()
    with pytest.raises(KeyError):
        rec.set("not_a_real_field", "x")


def test_record_tracks_confidence_separately():
    rec = IntakeRecord(applicant_ref="A-1")
    rec.set(
        "offense_convicted_of",
        "Murder in the first degree",
        ocr_confidence=0.72,
        extraction_confidence=0.9,
        source_passage="convicted of murder in the first degree",
    )
    f = rec.get("offense_convicted_of")
    assert f is not None
    assert f.ocr_confidence == 0.72
    assert f.extraction_confidence == 0.9


def test_record_by_category_keeps_catalog_order():
    rec = IntakeRecord()
    rec.set("sentence_received", "life")
    rec.set("offense_convicted_of", "murder")
    ordered = [f.key for f in rec.by_category(IntakeCategory.CONVICTION_DETAILS)]
    # offense_convicted_of precedes sentence_received in the catalog.
    assert ordered == ["offense_convicted_of", "sentence_received"]


def test_missing_near_universal_reports_gaps():
    rec = IntakeRecord()
    rec.set("applicant_full_name", "Jane Roe")
    missing = rec.missing_near_universal()
    assert "applicant_full_name" not in missing
    assert "claims_actual_innocence" in missing
    assert set(missing) <= {f.key for f in near_universal_fields()}
