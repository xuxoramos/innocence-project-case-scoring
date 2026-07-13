"""Intake-to-records retrieval (README v2 Section 5 flow + Section 6.6 states).

This is the seam the pivot was built around: given a structured
:class:`~risk_engine.intake.record.IntakeRecord`, find the public court records
that plausibly belong to *that* applicant, run them through the flagging
pipeline, and report the retrieval outcome using the three distinct states from
Section 6.6 — a gap (``NOT_FOUND``) is never conflated with a clean record
(``FOUND_NO_FLAGS``).

Matching is deliberately conservative and explainable (no ranking, no scoring of
the *case*): an applicant is matched to a candidate record on name + conviction
year, with the name as the primary signal and the year as soft corroboration.
There is intentionally **no geographic constraint** — the flagged elements
(discredited forensic methods, named-official histories, witness/evidence
circumstances) are checkable regardless of where the case was tried, so matching
never gates on jurisdiction (README v2 pivot: intake is the front door, not a
geographic scan). The whole thing is backend-agnostic — it works against any
registered :class:`~risk_engine.acquisition.AcquisitionSource` (the offline
fixture, CourtListener, or a future source) because it only uses the
``discover``/``fetch`` contract.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .acquisition import get_source
from .defense import defense_strategy_note
from .intake.record import IntakeRecord
from .models import Case, Document, Flag
from .packet import CasePacket, RecordSearch, RecordSearchStatus, assemble_packet
from .processing import Pipeline, default_pipeline
from .severity import seriousness_descriptor

#: Record types a chapter would expect to exist for a conviction. Appellate
#: opinions are the only kind the POC can retrieve online today (CourtListener);
#: trial transcripts and dockets are intentionally not wired up yet (Section
#: 6.5), so they surface as honest ``NOT_FOUND`` states rather than as "clean".
DEFAULT_EXPECTED_RECORDS: tuple[str, ...] = (
    "appellate opinion",
    "trial court docket",
    "post-conviction filings",
)

#: Minimum name similarity for a candidate to be considered the same person.
#: Tuned for sensitivity over precision (README 6.2): a borderline match is
#: surfaced for a human to confirm, a near-miss is dropped.
NAME_MATCH_FLOOR: float = 0.6

#: Appellate opinions are filed years after conviction, so the year is a soft
#: corroborating signal, not a hard gate. Within this many years counts as
#: consistent; outside it the match is kept but the year is flagged inconsistent.
YEAR_TOLERANCE: int = 15

#: Minimum retrieved opinion length (characters) to flag on (spec v3 item 5).
#: A live record shorter than this is treated as too thin to flag reliably and
#: surfaces as a gap, routing the reviewer to the manual-paste fallback.
MIN_RECORD_TEXT_CHARS: int = 1000

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_NONWORD_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")
# Tokens that say nothing about identity in a case caption.
_STOPWORDS = frozenset(
    {"commonwealth", "state", "people", "united", "states", "v", "vs", "versus", "in", "re", "ex"}
)


@dataclass(frozen=True)
class MatchCriteria:
    """The identifying facts pulled from an intake, used to match records."""

    full_name: str
    year: int | None


@dataclass(frozen=True)
class CandidateMatch:
    """A discovered case scored against the intake criteria."""

    case: Case
    name_score: float
    year_consistent: bool

    @property
    def is_match(self) -> bool:
        return self.name_score >= NAME_MATCH_FLOOR

    @property
    def confidence(self) -> float:
        """Match confidence — a consistent year nudges the name score, never above 1."""
        score = self.name_score
        if self.year_consistent:
            score += 0.05
        return min(score, 1.0)


@dataclass
class RetrievalResult:
    """Everything the retrieval step produced for one intake."""

    criteria: MatchCriteria
    candidates_considered: int
    matches: list[CandidateMatch] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)  # matched + processed
    record_searches: list[RecordSearch] = field(default_factory=list)
    #: Neutral descriptive record notes (e.g. trial-defense strategy, item 11).
    notes: list[str] = field(default_factory=list)

    @property
    def flags(self) -> list[Flag]:
        return [f for case in self.cases for f in case.flags]


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", _NONWORD_RE.sub(" ", (text or "").lower())).strip()


def criteria_from_intake(intake: IntakeRecord) -> MatchCriteria:
    """Pull the matchable identity facts from an intake record (name + year)."""
    name = intake.get("applicant_full_name")
    conviction = intake.get("date_of_conviction")
    year: int | None = None
    if conviction and conviction.value:
        m = _YEAR_RE.search(conviction.value)
        if m:
            year = int(m.group(0))
    return MatchCriteria(full_name=name.value if name else "", year=year)


def case_display_name(case: Case) -> str:
    """Best available human name for a discovered case (empty if none)."""
    return str(case.features.get("_cl_case_name", "") or "")


def identity_tokens(name: str) -> list[str]:
    """Distinctive name tokens (length >= 3, stopwords dropped), in order.

    The single source of truth for "which words in a name/caption carry
    identity," shared by :func:`name_score` and the offline bulk matcher so both
    tokenize captions identically.
    """
    return [t for t in _normalize(name).split() if len(t) >= 3 and t not in _STOPWORDS]


def surname_token(name: str) -> str | None:
    """The applicant's dominant identity token (their last distinctive word).

    This is the primary signal :func:`name_score` keys on, and the key the bulk
    matcher uses to index/look up candidate captions. ``None`` when the name has
    no usable token (so the caller records a gap rather than guessing).
    """
    tokens = identity_tokens(name)
    return tokens[-1] if tokens else None


def name_score(applicant: str, candidate: str) -> float:
    """How strongly an applicant name matches a candidate case caption (0..1).

    Captions read like ``Commonwealth v. Surname`` and usually carry only the
    surname, so the applicant's surname (their last distinctive token) appearing
    as a whole word in the caption is treated as the dominant identity signal,
    with additional token overlap and a fuzzy full-string ratio as corroboration
    for spelling and transpositions.
    """
    a = _normalize(applicant)
    c = _normalize(candidate)
    if not a or not c:
        return 0.0
    a_tokens = identity_tokens(applicant)
    c_tokens = set(identity_tokens(candidate))
    ratio = difflib.SequenceMatcher(None, a, c).ratio()
    if not a_tokens or not c_tokens:
        return ratio
    overlap = [t for t in a_tokens if t in c_tokens]
    surname = a_tokens[-1]
    if surname in c_tokens:
        extra = len([t for t in overlap if t != surname])
        return min(1.0, 0.8 + 0.1 * extra + 0.1 * ratio)
    coverage = len(overlap) / len(c_tokens)
    return max(ratio, 0.6 * coverage + 0.4 * ratio)


def score_candidate(criteria: MatchCriteria, case: Case) -> CandidateMatch:
    """Score one discovered case against the intake criteria (name + year)."""
    score = name_score(criteria.full_name, case_display_name(case))
    year_consistent = (
        criteria.year is not None
        and case.year is not None
        and abs(case.year - criteria.year) <= YEAR_TOLERANCE
    )
    return CandidateMatch(case=case, name_score=score, year_consistent=year_consistent)


def _case_text_len(case: Case) -> int:
    """Total normalized text length across a case's documents (spec v3 item 5)."""
    return sum(len(d.normalized_text or "") for d in case.documents)


def _classify_document(doc: Document) -> str:
    """Map a retrieved document to one of the expected record types."""
    uri = (doc.source_uri or "").lower()
    if "opinion" in uri or doc.media_type == "text/plain":
        return "appellate opinion"
    return "case record"


def _record_searches(
    cases: Sequence[Case], expected_records: Iterable[str]
) -> list[RecordSearch]:
    """Build the Section 6.6 record-search states for the matched cases.

    Every retrieved document becomes a ``FOUND_*`` entry (``FOUND_WITH_FLAGS``
    when its case produced any flag, else ``FOUND_NO_FLAGS``). Every expected
    record type that no document satisfied becomes a distinct ``NOT_FOUND`` —
    that is the whole point of 6.6: an absent record is reported as a gap, never
    as a clean result.
    """
    searches: list[RecordSearch] = []
    found_types: set[str] = set()
    for case in cases:
        status = (
            RecordSearchStatus.FOUND_WITH_FLAGS
            if case.flags
            else RecordSearchStatus.FOUND_NO_FLAGS
        )
        for doc in case.documents:
            rtype = _classify_document(doc)
            found_types.add(rtype)
            searches.append(
                RecordSearch(
                    record_type=rtype,
                    status=status,
                    detail=f"{case.case_id}:{doc.doc_id}",
                )
            )
    for expected in expected_records:
        if expected not in found_types:
            searches.append(
                RecordSearch(
                    record_type=expected,
                    status=RecordSearchStatus.NOT_FOUND,
                    detail="searched; no matching record retrieved",
                )
            )
    return searches


def retrieve_for_intake(
    intake: IntakeRecord,
    *,
    source_key: str,
    pipeline: Pipeline | None = None,
    expected_records: Iterable[str] = DEFAULT_EXPECTED_RECORDS,
    limit: int | None = 50,
    min_text_chars: int = 0,
) -> RetrievalResult:
    """Find, fetch, and flag the records that match an intake.

    Discovers candidates from ``source_key``, keeps the ones whose name (plus
    corroborating year/jurisdiction) matches the applicant, fetches and processes
    each through the flagging ``pipeline``, and assembles the Section 6.6 record
    states. Never ranks or scores the case; ``matches`` are ordered by match
    *confidence in the identity*, not by concern.

    ``min_text_chars`` (spec v3 item 5) drops a matched record whose retrieved
    text is too thin to flag reliably, so it surfaces as a gap and the reviewer
    is offered the manual-paste fallback rather than flags on a stub. Default 0
    (no threshold); the async save flow passes a real value for live sources.
    """
    source = get_source(source_key)
    criteria = criteria_from_intake(intake)
    pipeline = pipeline or default_pipeline()
    expected = tuple(expected_records)

    considered = 0
    matches: list[CandidateMatch] = []
    for candidate in source.discover(limit=limit):
        considered += 1
        scored = score_candidate(criteria, candidate)
        if scored.is_match:
            matches.append(scored)
    matches.sort(key=lambda m: m.confidence, reverse=True)

    cases: list[Case] = [pipeline.process(source.fetch(m.case)) for m in matches]
    if min_text_chars > 0:
        cases = [c for c in cases if _case_text_len(c) >= min_text_chars]
    # Attach the case-seriousness descriptor (spec v3 §3.4 severity axis) to every
    # flag from the offense the applicant reported. It is a per-element labelled
    # fact, never summed into a case-level number (README v2 §3.1).
    offense = intake.get("offense_convicted_of")
    seriousness = seriousness_descriptor(offense.value if offense else "")
    if seriousness:
        for case in cases:
            for flag in case.flags:
                flag.descriptors = {**flag.descriptors, **seriousness}
    # Neutral descriptive note: the trial-defense strategy stated in the record
    # (item 11). Not a flag, never scored.
    combined = " ".join(d.normalized_text or "" for c in cases for d in c.documents)
    note = defense_strategy_note(combined)
    return RetrievalResult(
        criteria=criteria,
        candidates_considered=considered,
        matches=matches,
        cases=cases,
        record_searches=_record_searches(cases, expected),
        notes=[note] if note else [],
    )


def build_packet_for_intake(
    intake: IntakeRecord,
    *,
    source_key: str,
    pipeline: Pipeline | None = None,
    expected_records: Iterable[str] = DEFAULT_EXPECTED_RECORDS,
    limit: int | None = 50,
    case_id: str | None = None,
    min_text_chars: int = 0,
) -> CasePacket:
    """End-to-end Section 5 flow: intake -> retrieval -> flags -> case packet."""
    result = retrieve_for_intake(
        intake,
        source_key=source_key,
        pipeline=pipeline,
        expected_records=expected_records,
        limit=limit,
        min_text_chars=min_text_chars,
    )
    return assemble_packet(
        case_id=case_id or intake.applicant_ref or "intake",
        intake=intake,
        flags=result.flags,
        records=result.record_searches,
        notes=result.notes,
    )


def packet_from_pasted_text(
    intake: IntakeRecord,
    text: str,
    *,
    case_id: str,
    pipeline: Pipeline | None = None,
) -> CasePacket:
    """Flag reviewer-pasted record text — the manual-paste fallback (spec v3 item 4).

    When live retrieval returns no usable record (or text too thin, item 5), the
    reviewer can paste the appellate-brief text. It is flagged by the same
    pipeline as a single ``pasted appellate text`` record, so the fallback path
    produces the same element flags and the same §6.6 record state as retrieval —
    never a score, never a guess about the pasted text's completeness.
    """
    pipeline = pipeline or default_pipeline()
    case = Case(case_id=case_id, jurisdiction="manual_paste")
    case.documents.append(
        Document(
            doc_id=f"{case_id}-PASTE",
            case_id=case_id,
            source_uri="manual-paste://appellate-text",
            media_type="text/plain",
            needs_ocr=False,
            normalized_text=text,
        )
    )
    case = pipeline.process(case)
    offense = intake.get("offense_convicted_of")
    seriousness = seriousness_descriptor(offense.value if offense else "")
    if seriousness:
        for flag in case.flags:
            flag.descriptors = {**flag.descriptors, **seriousness}
    status = (
        RecordSearchStatus.FOUND_WITH_FLAGS
        if case.flags
        else RecordSearchStatus.FOUND_NO_FLAGS
    )
    records = [
        RecordSearch(
            record_type="pasted appellate text",
            status=status,
            detail="manual paste by reviewer",
        )
    ]
    note = defense_strategy_note(text)
    return assemble_packet(
        case_id=case_id,
        intake=intake,
        flags=case.flags,
        records=records,
        notes=[note] if note else [],
    )
