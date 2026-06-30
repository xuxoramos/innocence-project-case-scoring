"""Tests for step 4 — per-element confidence calibration."""

from __future__ import annotations

from collections.abc import Iterable

from risk_engine.acquisition import register_source
from risk_engine.acquisition.base import AcquisitionSource
from risk_engine.calibration import (
    CALIBRATABLE_CATEGORIES,
    CalibrationStep,
    ElementMetrics,
    build_examples,
    calibrated_pipeline,
    evaluate,
    format_report,
    load_calibration,
    run_calibration,
    save_calibration,
)
from risk_engine.dataset import LabeledExample
from risk_engine.labels import ExonerationRecord
from risk_engine.models import Case, Document, Flag, FlagBasis, FlagCategory
from risk_engine.retrieval import CandidateMatch

FORENSIC = FlagCategory.DISCREDITED_FORENSIC_METHOD
PROSECUTOR = FlagCategory.PROSECUTOR_MISCONDUCT


class _CalSource(AcquisitionSource):
    """One named opinion that yields a discredited-forensic-method flag."""

    jurisdiction = "cal_test_src"
    display_name = "Calibration Test Source"

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        case = Case(case_id="C-0", jurisdiction=self.jurisdiction, year=1986)
        case.features["_cl_case_name"] = "Commonwealth v. Doswell"
        case.features["_text"] = "The conviction rested on bite-mark comparison evidence."
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


register_source(_CalSource())

# Minimal NRE CSV: one Pennsylvania record with the forensic factor set.
_NRE_HEADER = (
    "ID,Name,State,County of Crime,Worst Crime Display,Date of 1st Convic,"
    "Date of Crime Year,False or Misleading Forensic Evidence"
)
_NRE_ROW = "1,Thomas Doswell,Pennsylvania,Allegheny,Sexual Assault,1986-01-01,1986,Yes"


def _write_nre_csv(tmp_path):
    path = tmp_path / "fullcsv.csv"
    path.write_text(_NRE_HEADER + "\n" + _NRE_ROW + "\n", encoding="utf-8")
    return path



def _example(
    *,
    labels: set[FlagCategory],
    predicted: set[FlagCategory] | None,
) -> LabeledExample:
    """Build a labeled example; ``predicted=None`` means no matched record."""
    match = None
    if predicted is not None:
        case = Case(case_id="C", jurisdiction="j")
        for category in predicted:
            case.flags.append(
                Flag(category=category, basis=FlagBasis.DIRECTLY_STATED, extraction_confidence=0.5)
            )
        match = CandidateMatch(case=case, name_score=0.9, year_consistent=True)
    return LabeledExample(
        exoneration=ExonerationRecord(name="A B"),
        intake={},  # unused by evaluate()
        match=match,
        labels=labels,
    )


def test_role_misconduct_categories_are_calibratable():
    # The split made per-role official misconduct calibratable against NRE columns.
    for category in (
        FlagCategory.PROSECUTOR_MISCONDUCT,
        FlagCategory.JUDICIAL_MISCONDUCT,
        FlagCategory.POLICE_MISCONDUCT,
        FlagCategory.EXPERT_WITNESS_MISCONDUCT,
    ):
        assert category in CALIBRATABLE_CATEGORIES


def test_element_metrics_precision_recall_and_confidence():
    m = ElementMetrics(
        category=FORENSIC,
        true_positive=3,
        false_positive=1,
        false_negative=2,
        true_negative=4,
    )
    assert m.predicted == 4
    assert m.support == 5
    assert m.precision == 0.75
    assert m.recall == 0.6
    # The learned per-element confidence is the observed precision.
    assert m.calibrated_confidence == 0.75


def test_element_metrics_none_when_never_fired():
    m = ElementMetrics(category=FORENSIC, false_negative=2)
    assert m.precision is None
    assert m.calibrated_confidence is None
    assert m.recall == 0.0


def test_evaluate_counts_tp_fp_fn_and_calibrates():
    examples = [
        _example(labels={FORENSIC}, predicted={FORENSIC}),  # TP
        _example(labels=set(), predicted={FORENSIC}),  # FP
        _example(labels={FORENSIC}, predicted=set()),  # FN
        _example(labels=set(), predicted=set()),  # TN
    ]
    report = evaluate(examples, categories=[FORENSIC])
    metric = report.metrics[FORENSIC]
    assert (metric.true_positive, metric.false_positive) == (1, 1)
    assert (metric.false_negative, metric.true_negative) == (1, 1)
    assert metric.precision == 0.5
    assert report.scored == 4
    assert report.confidences()[FORENSIC] == 0.5


def test_evaluate_skips_unmatched_as_gap_not_false_negative():
    # An exoneration with no retrieved record is a §6.6 gap, not a missed flag.
    examples = [
        _example(labels={FORENSIC}, predicted=None),  # unmatched -> skipped
        _example(labels={FORENSIC}, predicted={FORENSIC}),  # TP
    ]
    report = evaluate(examples, categories=[FORENSIC])
    assert report.skipped_unmatched == 1
    assert report.scored == 1
    metric = report.metrics[FORENSIC]
    assert metric.false_negative == 0  # the gap was NOT charged as an FN
    assert metric.true_positive == 1


def test_save_and_load_roundtrip(tmp_path):
    table = {FORENSIC: 0.8, PROSECUTOR: 0.6}
    path = save_calibration(table, tmp_path / "calibration.json")
    assert load_calibration(path) == table


def test_load_missing_file_is_empty(tmp_path):
    assert load_calibration(tmp_path / "absent.json") == {}


def test_load_ignores_unknown_categories(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text('{"discredited_forensic_method": 0.8, "not_a_category": 0.9}')
    assert load_calibration(path) == {FORENSIC: 0.8}


def test_calibration_step_overrides_only_known_categories():
    case = Case(case_id="C", jurisdiction="j")
    case.flags.append(Flag(category=FORENSIC, basis=FlagBasis.DIRECTLY_STATED, extraction_confidence=0.5))
    case.flags.append(
        Flag(category=PROSECUTOR, basis=FlagBasis.DIRECTLY_STATED, extraction_confidence=0.4)
    )
    CalibrationStep({FORENSIC: 0.9}).run(case)
    by_cat = {f.category: f.extraction_confidence for f in case.flags}
    assert by_cat[FORENSIC] == 0.9  # rewritten
    assert by_cat[PROSECUTOR] == 0.4  # untouched (absent from table)


def test_calibration_step_does_not_apply_without_table_or_flags():
    case = Case(case_id="C", jurisdiction="j")
    case.flags.append(Flag(category=FORENSIC, basis=FlagBasis.DIRECTLY_STATED, extraction_confidence=0.5))
    assert CalibrationStep({}).applies_to(case) is False
    empty = Case(case_id="C2", jurisdiction="j")
    assert CalibrationStep({FORENSIC: 0.9}).applies_to(empty) is False


def test_calibrated_pipeline_appends_calibration_after_extraction():
    pipeline = calibrated_pipeline({FORENSIC: 0.95}, ocr=False)
    assert pipeline.steps[-1].name == "calibration"
    case = Case(case_id="C", jurisdiction="j")
    case.flags.append(Flag(category=FORENSIC, basis=FlagBasis.DIRECTLY_STATED, extraction_confidence=0.5))
    pipeline.steps[-1].run(case)
    assert case.flags[0].extraction_confidence == 0.95


def test_build_examples_links_each_record_to_predictions():
    record = ExonerationRecord(
        nre_id="1",
        name="Thomas Doswell",
        state="Pennsylvania",
        county="Allegheny",
        conviction_year=1986,
        factors={"False or Misleading Forensic Evidence"},
    )
    examples = build_examples([record], source_key="cal_test_src")
    assert len(examples) == 1
    example = examples[0]
    assert FORENSIC in example.labels  # NRE ground truth
    assert FORENSIC in example.predicted_categories  # pipeline fired on the match


def test_run_calibration_writes_table_and_scores(tmp_path):
    csv_path = _write_nre_csv(tmp_path)
    out = tmp_path / "calibration.json"
    report = run_calibration(
        csv_path, source_key="cal_test_src", save_path=out
    )
    assert report.scored == 1
    assert report.skipped_unmatched == 0
    # The forensic detector fired on the only case that truly had it -> precision 1.0.
    assert report.metrics[FORENSIC].precision == 1.0
    # The learned table was persisted and round-trips.
    assert load_calibration(out)[FORENSIC] == 1.0


def test_run_calibration_no_save_skips_write(tmp_path):
    csv_path = _write_nre_csv(tmp_path)
    out = tmp_path / "calibration.json"
    report = run_calibration(csv_path, source_key="cal_test_src", save_path=out, save=False)
    assert report.scored == 1
    assert not out.exists()


def test_format_report_flags_thin_support():
    # Judicial misconduct has tiny NRE support, so its line must be marked thin.
    examples = [_example(labels={FORENSIC}, predicted={FORENSIC})]
    report = evaluate(examples)
    text = format_report(report)
    assert "scored 1" in text
    assert "thin support" in text  # every category here has support < THIN_SUPPORT
