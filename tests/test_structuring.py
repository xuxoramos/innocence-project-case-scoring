"""Tests for the intake structuring layer."""

from __future__ import annotations

from risk_engine.intake import IntakeCategory, structure_intake


def test_maps_chapter_labels_via_aliases():
    rec = structure_intake(
        {
            "Inmate Number": "AB1234",
            "TDCJ Number": "9988",  # Texas label for the same field
            "Crime convicted of": "Murder",
        },
        chapter="TX",
    )
    # Both inmate-number variants resolve to the same schema key (last wins).
    assert rec.get("inmate_doc_id") is not None
    assert rec.get("offense_convicted_of").value == "Murder"


def test_exact_schema_key_gets_higher_confidence_than_alias():
    rec = structure_intake(
        {
            "offense_convicted_of": "Robbery",  # exact key
            "Sentence": "10 years",  # alias
        }
    )
    assert rec.get("offense_convicted_of").extraction_confidence == 0.95
    assert rec.get("sentence_received").extraction_confidence == 0.8


def test_unrecognized_label_is_kept_in_unmapped():
    rec = structure_intake({"Favorite color": "blue", "Full name": "Jane Roe"})
    assert rec.get("applicant_full_name").value == "Jane Roe"
    assert any("Favorite color" in u for u in rec.unmapped)


def test_blank_values_are_skipped():
    rec = structure_intake({"Full name": "  ", "Sentence": "life"})
    assert rec.get("applicant_full_name") is None
    assert rec.get("sentence_received").value == "life"


def test_ocr_confidence_passed_through_separately():
    rec = structure_intake(
        {"Full name": "Jane Roe"},
        ocr_confidences={"Full name": 0.66},
    )
    f = rec.get("applicant_full_name")
    assert f.ocr_confidence == 0.66
    assert f.extraction_confidence == 0.8  # alias mapping


def test_structured_record_groups_by_category():
    rec = structure_intake(
        {
            "Full name": "Jane Roe",
            "Sentence": "life",
            "Appeals status": "direct appeal denied",
        }
    )
    convictions = [f.key for f in rec.by_category(IntakeCategory.CONVICTION_DETAILS)]
    assert convictions == ["sentence_received"]
    post = [f.key for f in rec.by_category(IntakeCategory.POST_CONVICTION_HISTORY)]
    assert post == ["appeals_status"]
