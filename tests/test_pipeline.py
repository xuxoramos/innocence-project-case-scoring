"""End-to-end and unit tests for the scaffold."""

from __future__ import annotations

from risk_engine.acquisition import get_source, list_sources
from risk_engine.models import Case, Document, FlagBasis, FlagCategory
from risk_engine.processing import default_pipeline
from risk_engine.scoring import get_scorer, list_scorers


def test_sources_and_scorers_registered():
    assert "allegheny_pa" in list_sources()
    assert "flag_count" in list_scorers()


def test_full_pipeline_runs_and_ranks():
    source = get_source("allegheny_pa")
    pipeline = default_pipeline()
    cases = [pipeline.process(source.fetch(c)) for c in source.discover()]
    worklist = get_scorer("flag_count").rank(cases)
    assert len(worklist.entries) == 2
    assert [e.rank for e in worklist.entries] == [1, 2]


def test_ocr_step_optional_when_already_digitized():
    case = Case(case_id="X", jurisdiction="allegheny_pa")
    case.documents.append(
        Document(doc_id="X-1", case_id="X", needs_ocr=False, normalized_text="single witness only")
    )
    case = default_pipeline(ocr=False).process(case)
    assert case.has_tabular
    assert any(f.category is FlagCategory.WITNESS_RELIABILITY for f in case.flags)


def test_cross_racial_flag_marked_inferred():
    case = Case(case_id="Y", jurisdiction="allegheny_pa")
    case.documents.append(
        Document(doc_id="Y-1", case_id="Y", needs_ocr=False, normalized_text="cross-racial id")
    )
    case = default_pipeline(ocr=False).process(case)
    cr = [f for f in case.flags if f.category is FlagCategory.CROSS_RACIAL_EYEWITNESS_ID]
    assert cr and cr[0].basis is FlagBasis.INFERRED


def test_ranking_prefers_more_confident_directly_stated_flags():
    a = Case(case_id="A", jurisdiction="j")
    a.documents.append(Document(doc_id="A1", case_id="A", needs_ocr=False,
                                 normalized_text="single witness jailhouse informant"))
    b = Case(case_id="B", jurisdiction="j")
    b.documents.append(Document(doc_id="B1", case_id="B", needs_ocr=False,
                                 normalized_text="cross-racial id"))
    pipe = default_pipeline(ocr=False)
    cases = [pipe.process(a), pipe.process(b)]
    wl = get_scorer("flag_count").rank(cases)
    assert wl.entries[0].case.case_id == "A"
