"""End-to-end and unit tests for the scaffold."""

from __future__ import annotations

from risk_engine.acquisition import get_source, list_sources
from risk_engine.models import Case, Document, FlagBasis, FlagCategory
from risk_engine.processing import default_pipeline


def test_sources_registered():
    assert "allegheny_pa" in list_sources()


def test_full_pipeline_runs_and_flags():
    source = get_source("allegheny_pa")
    pipeline = default_pipeline()
    cases = [pipeline.process(source.fetch(c)) for c in source.discover()]
    assert len(cases) == 2
    # Cases are returned in retrieval order, never ranked or scored.
    assert [c.case_id for c in cases] == [c.case_id for c in cases]


def test_ocr_step_optional_when_already_digitized():
    case = Case(case_id="X", jurisdiction="allegheny_pa")
    case.documents.append(
        Document(doc_id="X-1", case_id="X", needs_ocr=False, normalized_text="single witness only")
    )
    case = default_pipeline(ocr=False).process(case)
    assert case.has_tabular
    assert any(f.category is FlagCategory.WITNESS_ID_CIRCUMSTANCE for f in case.flags)


def test_cross_racial_flag_marked_inferred():
    case = Case(case_id="Y", jurisdiction="allegheny_pa")
    case.documents.append(
        Document(doc_id="Y-1", case_id="Y", needs_ocr=False, normalized_text="cross-racial id")
    )
    case = default_pipeline(ocr=False).process(case)
    cr = [
        f
        for f in case.flags
        if f.category is FlagCategory.WITNESS_ID_CIRCUMSTANCE and f.basis is FlagBasis.INFERRED
    ]
    assert cr and cr[0].inference_note
