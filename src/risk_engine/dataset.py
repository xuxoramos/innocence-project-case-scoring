"""Labeled-dataset construction from NRE exonerations + their court records.

Throwaway evaluation/calibration tooling — **not** part of the live §5 intake
flow. It links a known exoneration (with its NRE structural-failure factor
labels) to the matching public court record and synthesizes the intake
questionnaire that applicant would have filed, producing:

  * realistic end-to-end fixtures for the §5 pipeline, and
  * a labeled ``intake -> known NRE factors`` dataset that step 4 uses to
    **calibrate the per-element flag confidences**. Calibration stays per
    element and is never aggregated into a case-level score or rank
    (README v2 §3.1 — the rejected case-level risk score).

Matching reuses :mod:`risk_engine.retrieval`'s name+year scoring against any
registered acquisition source, so it is backend-agnostic and offline-testable
with the same fake-source pattern the retrieval tests use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .acquisition import get_source
from .intake.record import IntakeRecord
from .labels import NRE_UNMAPPED_FACTOR_COLUMNS, ExonerationRecord
from .models import Case, FlagCategory
from .processing import Pipeline, default_pipeline
from .retrieval import CandidateMatch, MatchCriteria, score_candidate

#: Default source for matching exonerations: nationwide appellate opinions
#: (exonerations span every state, so the search is not geographically gated).
DEFAULT_EXONERATION_SOURCE = "appellate_cl"

#: Confidence stamped on back-filled intake fields. These are derived directly
#: from the NRE's structured columns, so *extraction* is certain; it is the
#: downstream *flagging* confidence (step 4) we are trying to learn, not this.
_BACKFILL_CONFIDENCE = 1.0


def criteria_from_exoneration(record: ExonerationRecord) -> MatchCriteria:
    """Identity facts for matching an exoneration to court records (name + year).

    Uses the conviction year when present (closest to the appellate caption's
    filing era), falling back to the crime year.
    """
    return MatchCriteria(
        full_name=record.name,
        year=record.conviction_year or record.crime_year,
    )


def match_exoneration(
    record: ExonerationRecord,
    *,
    source_key: str = DEFAULT_EXONERATION_SOURCE,
    limit: int | None = 50,
) -> CandidateMatch | None:
    """Find the best-matching court record for an exoneration, or ``None``.

    Discovers candidates from ``source_key`` and scores each on name + year
    exactly as the intake flow does, returning the highest-confidence *match*
    (``is_match``) or ``None`` when nothing clears the name floor. Live sources
    need their credentials; the offline fixture and test fakes need no network.
    """
    source = get_source(source_key)
    criteria = criteria_from_exoneration(record)
    best: CandidateMatch | None = None
    for candidate in source.discover(limit=limit):
        scored = score_candidate(criteria, candidate)
        if scored.is_match and (best is None or scored.confidence > best.confidence):
            best = scored
    return best


def _jurisdiction(record: ExonerationRecord) -> str:
    """Human-readable conviction jurisdiction from NRE county + state."""
    if record.county and record.state:
        return f"{record.county} County, {record.state}"
    return ", ".join(p for p in (record.county, record.state) if p)


def intake_from_exoneration(
    record: ExonerationRecord,
    *,
    applicant_ref: str | None = None,
) -> IntakeRecord:
    """Synthesize the intake an exonerated applicant *would* have filed.

    Back-fills only the schema fields the NRE's structured columns determine —
    name, conviction date, jurisdiction, offense, and the (true, by definition)
    actual-innocence claim. Narrative fields are left empty: the NRE carries no
    questionnaire prose, and inventing it would fabricate evidence. Every field
    records its NRE provenance in ``source_passage``.
    """
    rec = IntakeRecord(applicant_ref=applicant_ref or record.nre_id or record.name)

    def _set(key: str, value: object, column: str) -> None:
        if value:
            rec.set(
                key,
                str(value),
                extraction_confidence=_BACKFILL_CONFIDENCE,
                source_passage=f"NRE:{record.nre_id} {column}",
            )

    _set("applicant_full_name", record.name, "Name")
    _set("offense_convicted_of", record.crime, "Worst Crime Display")
    _set("conviction_jurisdiction", _jurisdiction(record), "County of Crime + State")
    _set("date_of_conviction", record.conviction_year, "Date of 1st Convic")
    _set("crime_date_time", record.crime_year, "Date of Crime Year")
    rec.set(
        "claims_actual_innocence",
        "Yes",
        extraction_confidence=_BACKFILL_CONFIDENCE,
        source_passage=f"NRE:{record.nre_id} exonerated",
    )
    return rec


@dataclass
class LabeledExample:
    """An exoneration linked to its court record, intake, and ground-truth labels."""

    exoneration: ExonerationRecord
    intake: IntakeRecord
    match: CandidateMatch | None = None
    #: FlagCategories the NRE says this case truly had — the step-4 ground truth.
    labels: set[FlagCategory] = field(default_factory=set)
    #: NRE failure factors with no schema-checkable counterpart (known blind spots).
    unmapped_factors: set[str] = field(default_factory=set)

    @property
    def matched_case(self) -> Case | None:
        return self.match.case if self.match else None

    @property
    def predicted_categories(self) -> set[FlagCategory]:
        """FlagCategories the pipeline actually emitted on the matched case."""
        case = self.matched_case
        return {f.category for f in case.flags} if case else set()


def build_labeled_example(
    record: ExonerationRecord,
    *,
    source_key: str = DEFAULT_EXONERATION_SOURCE,
    limit: int | None = 50,
    match: bool = True,
    pipeline: Pipeline | None = None,
) -> LabeledExample:
    """Assemble one labeled example: match (optional), back-fill, attach labels.

    With ``match=True`` (default) the exoneration is matched to a court record and
    the matched case is run through ``pipeline`` so its *predicted* flags can be
    compared against ``labels`` (the NRE ground truth) for per-element calibration.
    With ``match=False`` only the offline back-fill + labels are produced (no
    network, no source access).
    """
    candidate: CandidateMatch | None = None
    if match:
        candidate = match_exoneration(record, source_key=source_key, limit=limit)
        if candidate is not None:
            source = get_source(source_key)
            candidate = CandidateMatch(
                case=source.fetch(candidate.case),
                name_score=candidate.name_score,
                year_consistent=candidate.year_consistent,
            )
    return labeled_example_from_candidate(record, candidate, pipeline=pipeline)


def labeled_example_from_candidate(
    record: ExonerationRecord,
    candidate: CandidateMatch | None,
    *,
    pipeline: Pipeline | None = None,
) -> LabeledExample:
    """Assemble a labeled example from an *already-matched* candidate (or a gap).

    ``candidate`` must already carry its documents (the API path fetches them; the
    offline bulk path attaches them from the snapshot) — this runs ``pipeline`` on
    that case to record predicted flags, back-fills the intake, and attaches the
    NRE labels. ``candidate=None`` produces a gap row (no predictions, §6.6). This
    is the shared assembly step behind both the API and bulk backfills, so a match
    means the same thing regardless of how it was found.
    """
    final: CandidateMatch | None = None
    if candidate is not None:
        pipeline = pipeline or default_pipeline()
        final = CandidateMatch(
            case=pipeline.process(candidate.case),
            name_score=candidate.name_score,
            year_consistent=candidate.year_consistent,
        )
    return LabeledExample(
        exoneration=record,
        intake=intake_from_exoneration(record, applicant_ref=record.nre_id or None),
        match=final,
        labels=record.categories(),
        unmapped_factors={f for f in record.factors if f in NRE_UNMAPPED_FACTOR_COLUMNS},
    )
