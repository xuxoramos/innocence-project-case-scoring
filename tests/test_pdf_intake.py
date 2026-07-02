"""Tests for the offline PDF intake extraction, parsing, and prefill layer."""

from __future__ import annotations

import pytest

from risk_engine import pdf_intake
from risk_engine.casefiles import (
    case_pdf_path,
    looks_like_pdf,
    promote_staged_pdf,
    save_staged_pdf,
    staged_pdf_path,
)

_PDF_BYTES = b"%PDF-1.4 minimal fixture bytes for tests"


def test_parse_intake_pairs_lifts_label_value_lines():
    text = (
        "Name of applicant: Lee Doe\n"
        "Offense: Second-degree murder\n"
        "County of conviction: Allegheny\n"
        "\n"
        "This is a narrative paragraph, not a field, and should be ignored.\n"
        "   Sentence : Life without parole  \n"
    )
    pairs = pdf_intake.parse_intake_pairs(text)
    assert pairs["Name of applicant"] == "Lee Doe"
    assert pairs["Offense"] == "Second-degree murder"
    assert pairs["County of conviction"] == "Allegheny"
    assert pairs["Sentence"] == "Life without parole"
    # A prose line with no colon-delimited label must not become a field.
    assert not any("narrative paragraph" in k for k in pairs)


def test_parse_intake_pairs_first_label_wins():
    text = "Name: First Value\nName: Second Value\n"
    assert pdf_intake.parse_intake_pairs(text) == {"Name": "First Value"}


def test_extract_pdf_text_prefers_embedded(monkeypatch):
    monkeypatch.setattr(pdf_intake, "_embedded_text", lambda p: "x" * 100)
    monkeypatch.setattr(pdf_intake, "_ocr_text", lambda p: "should not be used")
    text, method = pdf_intake.extract_pdf_text("/tmp/whatever.pdf")
    assert method == "embedded"
    assert text == "x" * 100


def test_extract_pdf_text_falls_back_to_ocr_when_no_embedded(monkeypatch):
    monkeypatch.setattr(pdf_intake, "_embedded_text", lambda p: "   ")
    monkeypatch.setattr(pdf_intake, "_ocr_text", lambda p: "recovered by ocr")
    text, method = pdf_intake.extract_pdf_text("/tmp/scan.pdf")
    assert method == "ocr"
    assert text == "recovered by ocr"


def test_extract_pdf_text_none_when_nothing_extracted(monkeypatch):
    monkeypatch.setattr(pdf_intake, "_embedded_text", lambda p: "")
    monkeypatch.setattr(pdf_intake, "_ocr_text", lambda p: "")
    text, method = pdf_intake.extract_pdf_text("/tmp/empty.pdf")
    assert method == "none"
    assert text == ""


def test_prefill_maps_known_labels_and_keeps_unmapped(monkeypatch):
    text = (
        "Full name: Lee Doe\n"
        "Offense: Second-degree murder\n"
        "Favorite color: teal\n"
    )
    monkeypatch.setattr(pdf_intake, "extract_pdf_text", lambda p: (text, "embedded"))
    intake, raw, method = pdf_intake.prefill_intake_from_pdf("/tmp/x.pdf", chapter="PA")

    assert method == "embedded"
    assert raw == text
    assert intake.get("applicant_full_name").value == "Lee Doe"
    assert intake.get("offense_convicted_of").value == "Second-degree murder"
    # An unrecognised label is preserved, never dropped or invented into a field.
    assert any("Favorite color: teal" in u for u in intake.unmapped)


def test_looks_like_pdf():
    assert looks_like_pdf(_PDF_BYTES)
    assert not looks_like_pdf(b"not a pdf")
    assert not looks_like_pdf(b"")


def test_save_and_promote_staged_pdf(tmp_path):
    staging = tmp_path / "staging"
    stored = tmp_path / "stored"
    token = "tok123abc"
    case_id = "CF-abc123"

    save_staged_pdf(token, _PDF_BYTES, base_dir=staging)
    assert staged_pdf_path(token, base_dir=staging).read_bytes() == _PDF_BYTES

    promoted = promote_staged_pdf(token, case_id, staging_dir=staging, pdf_dir=stored)
    assert promoted is True
    assert case_pdf_path(case_id, base_dir=stored).read_bytes() == _PDF_BYTES
    # The staged copy is moved, not left behind.
    assert not staged_pdf_path(token, base_dir=staging).exists()


def test_promote_missing_staged_returns_false(tmp_path):
    assert (
        promote_staged_pdf(
            "nope", "CF-x", staging_dir=tmp_path / "s", pdf_dir=tmp_path / "d"
        )
        is False
    )


def test_path_helpers_reject_unsafe_handles():
    with pytest.raises(ValueError):
        staged_pdf_path("../escape")
    with pytest.raises(ValueError):
        case_pdf_path("a/b")
