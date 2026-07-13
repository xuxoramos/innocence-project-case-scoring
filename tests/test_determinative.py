"""Unit tests for the outcome-determinative record-language step."""

from __future__ import annotations

from risk_engine.models import Case, Document, FlagCategory
from risk_engine.processing import default_pipeline


def _case_with(text: str) -> Case:
    case = Case(case_id="D", jurisdiction="j")
    case.documents.append(
        Document(doc_id="D1", case_id="D", needs_ocr=False, normalized_text=text)
    )
    return default_pipeline(ocr=False).process(case)


def _flag(case: Case, category: FlagCategory):
    return next((f for f in case.flags if f.category is category), None)


def test_witness_id_signal_attached_to_the_eyewitness_flag():
    case = _case_with(
        "The victim identified him at a suggestive lineup. The prosecutor told the "
        "jury the eyewitness identification was the only evidence of guilt."
    )
    flag = _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE)
    assert flag is not None
    # The flag itself came from the first sentence; the determinative signal is
    # the second, verbatim, and stored as a separate descriptor.
    assert "suggestive lineup" in flag.source_passage
    assert (
        flag.descriptors["record_signal"]
        == "The prosecutor told the jury the eyewitness identification was the "
        "only evidence of guilt."
    )
    assert flag.descriptors["signal_basis"].startswith("the record's own wording")


def test_informant_signal_attached_to_the_informant_flag():
    case = _case_with(
        "A jailhouse informant testified against him. On appeal the court noted the "
        "case rested entirely on the informant's testimony."
    )
    flag = _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE)
    assert flag is not None
    assert "rested entirely on the informant" in flag.descriptors["record_signal"]
    assert "signal_basis" in flag.descriptors


def test_no_determinative_language_leaves_no_signal():
    case = _case_with("A jailhouse informant testified against him at trial.")
    flag = _flag(case, FlagCategory.INFORMANT_CIRCUMSTANCE)
    assert flag is not None
    assert "record_signal" not in flag.descriptors


def test_signal_for_a_different_element_does_not_attach():
    # A determinative frame that names an unrelated element (a fingerprint) must
    # not hang a signal on the eyewitness flag.
    case = _case_with(
        "The victim identified him at a suggestive lineup. The court said the "
        "fingerprint was the only evidence."
    )
    flag = _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE)
    assert flag is not None
    assert "record_signal" not in flag.descriptors


def test_determinative_language_never_fabricates_a_flag():
    # Frame + element noun are present, but no underlying lexeme flag exists, so
    # nothing is attached and no flag is invented (gated by an existing flag).
    case = _case_with(
        "The case turned entirely on the eyewitness account, with little else in the record."
    )
    assert _flag(case, FlagCategory.WITNESS_ID_CIRCUMSTANCE) is None
