"""Tests for the discredited-forensic-method reference and step."""

from __future__ import annotations

from risk_engine.config import settings
from risk_engine.forensic import (
    FORENSIC_METHOD_REFERENCE,
    find_forensic_methods,
)
from risk_engine.models import Case, Document, FlagBasis, FlagCategory
from risk_engine.processing.forensic import ForensicMethodStep


def _case_with(text: str) -> Case:
    case = Case(case_id="F", jurisdiction="j")
    case.documents.append(
        Document(doc_id="F1", case_id="F", needs_ocr=False, normalized_text=text)
    )
    return case


def test_reference_entries_all_carry_a_source():
    assert FORENSIC_METHOD_REFERENCE
    for ref in FORENSIC_METHOD_REFERENCE:
        assert ref.source.strip()
        assert 0.0 < ref.confidence <= 1.0


def test_finds_method_and_aliases():
    hits = find_forensic_methods("The state relied on bite mark testimony at trial.")
    assert len(hits) == 1
    assert hits[0].ref.method == "bite-mark comparison"


def test_one_hit_per_method():
    text = "Bite-mark comparison was used. The bite mark evidence was central."
    hits = find_forensic_methods(text)
    methods = [h.ref.method for h in hits]
    assert methods.count("bite-mark comparison") == 1


def test_no_false_positive_on_unrelated_text():
    assert find_forensic_methods("The eyewitness identified the defendant.") == []


def test_step_emits_flag_with_verification_source():
    case = _case_with("A forensic odontologist testified using bite-mark comparison.")
    case = ForensicMethodStep().run(case)
    forensic = [f for f in case.flags if f.category is FlagCategory.DISCREDITED_FORENSIC_METHOD]
    assert len(forensic) == 1
    flag = forensic[0]
    assert flag.basis is FlagBasis.DIRECTLY_STATED
    assert flag.verification_source and "bite-mark comparison" in flag.verification_source
    assert "bite-mark comparison" in flag.source_passage


def test_below_floor_method_is_suppressed():
    # firearm/toolmark identification confidence (0.7) sits at/above the default
    # floor; force the floor above it to confirm suppression is wired.
    case = _case_with("An examiner gave firearm identification testimony.")
    original = settings.confidence_floor
    try:
        settings.confidence_floor = 0.95
        case = ForensicMethodStep().run(case)
    finally:
        settings.confidence_floor = original
    assert not any(
        f.category is FlagCategory.DISCREDITED_FORENSIC_METHOD for f in case.flags
    )
