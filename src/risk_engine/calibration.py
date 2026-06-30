"""Step 4 — per-element confidence calibration against NRE ground truth.

This is the calibration half of the exoneration chain (:mod:`risk_engine.dataset`
builds the labeled examples; this module learns from them). For each flag
*category* it measures how often the pipeline's prediction agrees with the NRE
factor label across many matched cases, and turns that agreement rate into a
**calibrated per-element confidence** — the empirical probability that a fired
flag of that category is real. That learned value replaces the hand-picked
extraction confidences (e.g. :mod:`risk_engine.processing.tabular`'s seed values)
when a calibration table is applied.

Three constraints make this safe under README v2:

* **Per element, never a case score (§3.1).** Calibration aggregates one
  category's outcomes *across cases* to rate that category's reliability. It
  never combines the different flags of a single case into one number, rank, or
  probability. Each flag stays standalone.
* **Gaps are not misses (§6.6).** Only examples whose court record was actually
  retrieved are scored. An exoneration with no matching record is a retrieval
  gap, not a detector failure, so it is excluded from precision/recall rather
  than counted as a false negative.
* **Per-role official misconduct is calibratable (§6.5).** The NRE codes
  misconduct per actor (prosecutor / judge / police / forensic analyst) as its
  own Yes/No column, which is case-level ground truth for the matching
  per-role flag. So those four categories *are* in
  :data:`CALIBRATABLE_CATEGORIES`. What stays uncalibratable is the *named
  individual* — the NRE carries no official names, so calibration validates
  "was there prosecutor misconduct in this case," never "is this named
  prosecutor the one at fault." The undivided "Official Misconduct" rollup is
  left unmapped to avoid double-counting the role columns.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .dataset import DEFAULT_EXONERATION_SOURCE, LabeledExample, build_labeled_example
from .labels import DEFAULT_NRE_CSV, NRE_FACTOR_COLUMNS, ExonerationRecord, load_known_exonerations
from .models import Case, FlagCategory
from .processing import Pipeline, ProcessingStep, default_pipeline

#: Categories that have NRE factor-column ground truth and can be calibrated.
#: This is exactly the image of the NRE factor mapping, which now includes the
#: four per-role misconduct categories (the NRE codes misconduct per actor); the
#: undivided "Official Misconduct" rollup is left unmapped (see module docs).
CALIBRATABLE_CATEGORIES: frozenset[FlagCategory] = frozenset(NRE_FACTOR_COLUMNS.values())

#: Where a learned calibration table is persisted by default.
DEFAULT_CALIBRATION_PATH: Path = settings.processed_dir / "calibration.json"


@dataclass(frozen=True)
class ElementMetrics:
    """Confusion counts and per-element metrics for one flag category."""

    category: FlagCategory
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0

    @property
    def predicted(self) -> int:
        """How many scored cases fired this category."""
        return self.true_positive + self.false_positive

    @property
    def support(self) -> int:
        """How many scored cases truly had this category (NRE ground truth)."""
        return self.true_positive + self.false_negative

    @property
    def precision(self) -> float | None:
        """P(category truly present | flag fired). ``None`` when it never fired."""
        return self.true_positive / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        """P(flag fired | category truly present). ``None`` when no support."""
        return self.true_positive / self.support if self.support else None

    @property
    def calibrated_confidence(self) -> float | None:
        """The learned per-element confidence = observed precision.

        This is the probability a fired flag of this category is real, which is
        exactly what a flag's ``extraction_confidence`` should express. ``None``
        when the category never fired (no evidence to calibrate from — leave the
        extractor's own value in place).
        """
        return self.precision


@dataclass
class CalibrationReport:
    """Per-category metrics learned from a batch of labeled examples."""

    metrics: dict[FlagCategory, ElementMetrics] = field(default_factory=dict)
    #: Number of examples actually scored (matched + processed). Unmatched
    #: examples are excluded (§6.6) and counted here for transparency.
    scored: int = 0
    skipped_unmatched: int = 0

    def confidences(self) -> dict[FlagCategory, float]:
        """The calibration table: category -> learned confidence (fired only)."""
        return {
            category: metric.calibrated_confidence
            for category, metric in self.metrics.items()
            if metric.calibrated_confidence is not None
        }


def evaluate(
    examples: Iterable[LabeledExample],
    *,
    categories: Iterable[FlagCategory] = CALIBRATABLE_CATEGORIES,
) -> CalibrationReport:
    """Score predictions against NRE labels and build per-element metrics.

    Only examples with a matched, processed court record are scored — an
    exoneration we could not link to a record is a retrieval gap, not a missed
    flag, so it is skipped (§6.6) rather than charged as a false negative.
    """
    cats = tuple(categories)
    tp = {c: 0 for c in cats}
    fp = {c: 0 for c in cats}
    fn = {c: 0 for c in cats}
    tn = {c: 0 for c in cats}
    scored = 0
    skipped = 0
    for example in examples:
        if example.matched_case is None:
            skipped += 1
            continue
        scored += 1
        predicted = example.predicted_categories
        actual = example.labels
        for category in cats:
            in_pred = category in predicted
            in_actual = category in actual
            if in_pred and in_actual:
                tp[category] += 1
            elif in_pred:
                fp[category] += 1
            elif in_actual:
                fn[category] += 1
            else:
                tn[category] += 1
    metrics = {
        c: ElementMetrics(
            category=c,
            true_positive=tp[c],
            false_positive=fp[c],
            false_negative=fn[c],
            true_negative=tn[c],
        )
        for c in cats
    }
    return CalibrationReport(metrics=metrics, scored=scored, skipped_unmatched=skipped)


def save_calibration(
    confidences: dict[FlagCategory, float],
    path: str | Path = DEFAULT_CALIBRATION_PATH,
) -> Path:
    """Persist a calibration table (category value -> confidence) as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {category.value: conf for category, conf in confidences.items()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_calibration(
    path: str | Path = DEFAULT_CALIBRATION_PATH,
) -> dict[FlagCategory, float]:
    """Load a calibration table, or return ``{}`` if the file is absent.

    Unknown category keys are ignored so a stale table never breaks the run.
    """
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    table: dict[FlagCategory, float] = {}
    for key, value in raw.items():
        try:
            table[FlagCategory(key)] = float(value)
        except (ValueError, TypeError):
            continue
    return table


class CalibrationStep(ProcessingStep):
    """Rewrite each fired flag's ``extraction_confidence`` to its learned value.

    A pure confidence calibration: it only updates the confidence of flags whose
    category is in the table, leaving every other flag untouched. It never adds
    or removes flags (suppression stays the extractor's job) and never combines
    flags into a case-level number (§3.1). Categories absent from the table keep
    the extractor's own confidence.
    """

    name = "calibration"

    def __init__(
        self,
        confidences: dict[FlagCategory, float] | None = None,
        *,
        path: str | Path = DEFAULT_CALIBRATION_PATH,
    ):
        self.confidences = confidences if confidences is not None else load_calibration(path)

    def applies_to(self, case: Case) -> bool:
        return bool(self.confidences) and bool(case.flags)

    def run(self, case: Case) -> Case:
        for flag in case.flags:
            learned = self.confidences.get(flag.category)
            if learned is not None:
                flag.extraction_confidence = learned
        return case


def calibrated_pipeline(
    confidences: dict[FlagCategory, float] | None = None,
    *,
    path: str | Path = DEFAULT_CALIBRATION_PATH,
    base: Pipeline | None = None,
    **default_pipeline_kwargs: bool,
) -> Pipeline:
    """Return a pipeline that applies calibrated confidences after extraction.

    Builds on ``base`` (or :func:`default_pipeline`) and appends a
    :class:`CalibrationStep`, so flags are extracted normally and then have their
    per-element confidences replaced with the learned values.
    """
    base = base or default_pipeline(**default_pipeline_kwargs)
    return Pipeline([*base.steps, CalibrationStep(confidences, path=path)])


#: Below this NRE support count a category's precision rests on too few cases to
#: trust; the report marks it so a thin estimate is never read as settled.
THIN_SUPPORT = 20


def build_examples(
    records: Iterable[ExonerationRecord],
    *,
    source_key: str = DEFAULT_EXONERATION_SOURCE,
    match_limit: int = 50,
    pipeline: Pipeline | None = None,
) -> list[LabeledExample]:
    """Link each exoneration to its court record and pipeline predictions.

    One network round trip per record (discover + fetch against ``source_key``),
    so callers should bound the input. Records that match no record still come
    back as examples — :func:`evaluate` treats them as gaps, not misses.
    """
    return [
        build_labeled_example(
            record, source_key=source_key, limit=match_limit, pipeline=pipeline
        )
        for record in records
    ]


def run_calibration(
    csv_path: str | Path = DEFAULT_NRE_CSV,
    *,
    source_key: str = DEFAULT_EXONERATION_SOURCE,
    state: str | None = None,
    county: str | None = None,
    max_records: int | None = None,
    match_limit: int = 50,
    pipeline: Pipeline | None = None,
    save_path: str | Path = DEFAULT_CALIBRATION_PATH,
    save: bool = True,
) -> CalibrationReport:
    """Run the whole step-4 chain once and (optionally) persist the table.

    Loads NRE exonerations, links each to its court record, scores the pipeline's
    predictions against the NRE factor labels, and writes the learned per-element
    confidences to ``save_path``. This is a **batch** job, not a service: re-run
    it after changing the detectors or to refresh against a newer NRE snapshot.
    ``state``/``county`` scope the reference subset; ``max_records`` bounds the
    number of live record lookups.
    """
    records = load_known_exonerations(csv_path, state=state, county=county)
    if max_records is not None:
        records = records[:max_records]
    examples = build_examples(
        records, source_key=source_key, match_limit=match_limit, pipeline=pipeline
    )
    report = evaluate(examples)
    if save:
        save_calibration(report.confidences(), save_path)
    return report


def format_report(report: CalibrationReport) -> str:
    """Render a calibration report as plain text, honest about thin support.

    Shows, per category, how often the flag fired, how many cases truly had it
    (NRE support), the observed precision/calibrated confidence, and a ``(thin)``
    marker when support is too small to trust. Never combines categories into a
    single number.
    """
    lines = [
        f"Calibration: scored {report.scored} matched case(s), "
        f"skipped {report.skipped_unmatched} unmatched (retrieval gaps, not misses).",
        "",
        f"{'category':<28}{'fired':>7}{'support':>9}{'precision':>11}  notes",
    ]
    for category, metric in report.metrics.items():
        precision = "n/a" if metric.precision is None else f"{metric.precision:.2f}"
        notes = []
        if metric.support < THIN_SUPPORT:
            notes.append("thin support")
        if metric.predicted == 0:
            notes.append("never fired; confidence left as set")
        lines.append(
            f"{category.value:<28}{metric.predicted:>7}{metric.support:>9}"
            f"{precision:>11}  {', '.join(notes)}"
        )
    return "\n".join(lines)
