"""Persistent store of exoneration-backfilled intakes (the browse/analytics side).

The intake flow (§5) processes one *live* applicant at a time and is stateless.
This module persists the *other* population the project already constructs:
confirmed exonerations turned into the **same** intake schema by
:func:`risk_engine.dataset.intake_from_exoneration`, each carrying the NRE's
ground-truth factor labels and — when a court record was matched — the flags the
engine independently produced. Persisting them gives a searchable, analyzable
case set without ever leaving the project's rails:

* **Confirmed, not scored (§3.1/§3.2).** Every stored case is a *real, already
  adjudicated* exoneration. Nothing here is a still-incarcerated person labeled
  by similarity, and there is no case-level score, rank, or composite — analytics
  aggregate one factor/category *across* cases (descriptive), never collapse a
  single case into a number.
* **Gap is not clean (§6.6).** A case whose court record could not be matched is
  stored with ``matched=False`` and **no predicted flags**; it is a retrieval
  gap, kept distinct from a matched case that simply produced no flags. Analytics
  that compare predictions to labels count *matched cases only*.
* **Confirmed-vs-open never commingled.** This store holds exoneration-sourced
  records exclusively (``provenance="nre_exoneration"``); live applicant intakes
  are never written here.

Population is offline-capable: ``match=False`` backfills the intake + labels with
no network (gap rows), while ``match=True`` also links the court record and runs
the pipeline so predicted flags are recorded.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import settings
from .dataset import DEFAULT_EXONERATION_SOURCE, LabeledExample, build_labeled_example
from .innocence_project import tag_cases
from .labels import ExonerationRecord
from .models import FlagCategory
from .processing import Pipeline

#: Where the backfilled case store is persisted by default (JSON Lines).
DEFAULT_CASE_STORE_PATH: Path = settings.processed_dir / "case_store.jsonl"

#: Provenance stamped on every row: this store is exoneration-sourced only.
PROVENANCE_NRE = "nre_exoneration"

#: Below this matched-support count an agreement estimate rests on too few cases
#: to trust; analytics mark it so a thin number is never read as settled (§6.6
#: keeps gaps out of the denominator, so support is matched cases only).
THIN_SUPPORT = 20


@dataclass(frozen=True)
class StoredFlag:
    """A single engine-produced flag, flattened for persistence/display."""

    category: str
    basis: str
    extraction_confidence: float
    source_passage: str
    verification_source: str | None = None


@dataclass
class StoredCase:
    """One confirmed exoneration as a backfilled intake plus engine output.

    ``labels`` are the NRE ground-truth factor categories; ``predicted`` are the
    categories the pipeline emitted on the matched court record (empty when the
    record was not matched — a gap, not a clean result).
    """

    provenance: str
    nre_id: str
    name: str
    state: str
    county: str
    crime: str
    crime_year: int | None
    conviction_year: int | None
    #: Whether a court record was matched. ``False`` => gap, no predictions (§6.6).
    matched: bool
    #: NRE ground-truth FlagCategory values present in this exoneration.
    labels: list[str] = field(default_factory=list)
    #: NRE failure factors with no schema-checkable counterpart (known blind spots).
    unmapped_factors: list[str] = field(default_factory=list)
    #: FlagCategory values the pipeline emitted on the matched case.
    predicted: list[str] = field(default_factory=list)
    flags: list[StoredFlag] = field(default_factory=list)
    #: Whether this exoneration was secured by the Innocence Project. External
    #: metadata joined from their public case list (see ``innocence_project``);
    #: recomputed on load, so the persisted value is advisory.
    innocence_project: bool = False

    @property
    def jurisdiction(self) -> str:
        if self.county and self.state:
            return f"{self.county} County, {self.state}"
        return ", ".join(p for p in (self.county, self.state) if p)

    def to_intake(self):
        """Rebuild the intake this exoneree *would* have filed (§5.1 schema).

        Reverses the back-fill: the same NRE-derived fields
        :func:`risk_engine.dataset.intake_from_exoneration` populates (name,
        offense, jurisdiction, conviction/crime dates, the actual-innocence
        claim), so the detail view can show a stored case as a filled intake
        form. Narrative fields stay empty — the NRE carries no questionnaire
        prose, and inventing it would fabricate evidence (§3.2).
        """
        from .dataset import intake_from_exoneration

        return intake_from_exoneration(
            ExonerationRecord(
                nre_id=self.nre_id,
                name=self.name,
                state=self.state,
                county=self.county,
                crime=self.crime,
                crime_year=self.crime_year,
                conviction_year=self.conviction_year,
            )
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "StoredCase":
        flags = [StoredFlag(**f) for f in raw.get("flags", [])]
        data = {k: v for k, v in raw.items() if k != "flags"}
        return cls(**data, flags=flags)


def stored_from_example(example: LabeledExample) -> StoredCase:
    """Flatten a :class:`LabeledExample` into a persistable :class:`StoredCase`."""
    rec: ExonerationRecord = example.exoneration
    matched = example.matched_case is not None
    flags: list[StoredFlag] = []
    if matched:
        for flag in example.matched_case.flags:  # type: ignore[union-attr]
            flags.append(
                StoredFlag(
                    category=flag.category.value,
                    basis=flag.basis.value,
                    extraction_confidence=flag.extraction_confidence,
                    source_passage=" ".join(flag.source_passage.split()),
                    verification_source=flag.verification_source,
                )
            )
    return StoredCase(
        provenance=PROVENANCE_NRE,
        nre_id=rec.nre_id,
        name=rec.name,
        state=rec.state,
        county=rec.county,
        crime=rec.crime,
        crime_year=rec.crime_year,
        conviction_year=rec.conviction_year,
        matched=matched,
        labels=sorted(c.value for c in example.labels),
        unmapped_factors=sorted(example.unmapped_factors),
        predicted=sorted(c.value for c in example.predicted_categories),
        flags=flags,
    )


def save_cases(
    cases: Iterable[StoredCase],
    path: str | Path = DEFAULT_CASE_STORE_PATH,
) -> Path:
    """Persist stored cases as JSON Lines, one case per line (atomic write).

    Writes to a sibling ``.tmp`` file and renames it into place so a process
    killed mid-write never leaves a half-written store — the basis for the
    resumable backfill, where the file is rewritten after every record.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case.to_dict(), sort_keys=True))
            fh.write("\n")
    os.replace(tmp, path)
    return path


def load_cases(path: str | Path = DEFAULT_CASE_STORE_PATH) -> list[StoredCase]:
    """Load stored cases from JSON Lines, or ``[]`` when the file is absent."""
    path = Path(path)
    if not path.exists():
        return []
    cases: list[StoredCase] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(StoredCase.from_dict(json.loads(line)))
    return cases


#: Progress callback signature: ``(done, total, status, case)`` where ``status``
#: is ``"matched"``, ``"gap"``, or ``"cached"`` (already present from a prior run).
ProgressFn = Callable[[int, int, str, "StoredCase"], None]


def _default_progress(done: int, total: int, status: str, case: StoredCase) -> None:
    """Emit one line of per-record progress to stderr (stdout stays clean)."""
    year = case.conviction_year or case.crime_year or "?"
    print(
        f"[{done}/{total}] {status:<7} {case.name} ({case.state}, {year})",
        file=sys.stderr,
        flush=True,
    )


def backfill_cases(
    records: Iterable[ExonerationRecord],
    *,
    match: bool = True,
    source_key: str = DEFAULT_EXONERATION_SOURCE,
    match_limit: int = 50,
    pipeline: Pipeline | None = None,
    progress: ProgressFn | None = None,
) -> list[StoredCase]:
    """Build stored cases from exonerations (no persistence).

    With ``match=False`` this is fully offline: each exoneration is back-filled
    into the intake schema with its NRE labels but no court-record lookup, so the
    rows are gaps (no predictions). With ``match=True`` each exoneration is linked
    to its court record and run through ``pipeline`` so predicted flags are
    recorded (one network round trip per record — bound the input). ``progress``,
    if given, is called once per record. For a long, restartable run that also
    persists as it goes, use :func:`backfill_store`.
    """
    records = list(records)
    total = len(records)
    out: list[StoredCase] = []
    for done, record in enumerate(records, 1):
        case = stored_from_example(
            build_labeled_example(
                record,
                source_key=source_key,
                limit=match_limit,
                match=match,
                pipeline=pipeline,
            )
        )
        out.append(case)
        if progress is not None:
            progress(done, total, "matched" if case.matched else "gap", case)
    return out


def backfill_store(
    records: Iterable[ExonerationRecord],
    *,
    path: str | Path = DEFAULT_CASE_STORE_PATH,
    match: bool = True,
    source_key: str = DEFAULT_EXONERATION_SOURCE,
    match_limit: int = 50,
    pipeline: Pipeline | None = None,
    resume: bool = True,
    progress: ProgressFn | None = _default_progress,
) -> list[StoredCase]:
    """Backfill exonerations into the store, persisting after every record.

    Built for the long, rate-limited matched run: each record is written to
    ``path`` as soon as it is processed (atomic rewrite), so a killed process
    loses at most one record. With ``resume=True`` (default) records already
    present in the store are skipped, keyed by ``nre_id``. A matched run keeps an
    existing *matched* row but re-does an existing *gap* row to upgrade it; an
    offline (``match=False``) run keeps any existing row and never downgrades a
    match to a gap. ``progress`` defaults to a one-line-per-record stderr log;
    pass ``None`` to silence it.
    """
    records = list(records)
    total = len(records)
    path = Path(path)
    by_id: dict[str, StoredCase] = (
        {case.nre_id: case for case in load_cases(path)} if resume else {}
    )
    for done, record in enumerate(records, 1):
        key = record.nre_id or f"_row_{done}"
        prior = by_id.get(key)
        if prior is not None and (prior.matched or not match):
            if progress is not None:
                progress(done, total, "cached", prior)
            continue
        case = stored_from_example(
            build_labeled_example(
                record,
                source_key=source_key,
                limit=match_limit,
                match=match,
                pipeline=pipeline,
            )
        )
        by_id[key] = case
        save_cases(by_id.values(), path)
        if progress is not None:
            progress(done, total, "matched" if case.matched else "gap", case)
    return list(by_id.values())


def backfill_store_bulk(
    records: Iterable[ExonerationRecord],
    *,
    clusters_path: str | Path,
    opinions_path: str | Path | None = None,
    path: str | Path = DEFAULT_CASE_STORE_PATH,
    pipeline: Pipeline | None = None,
    resume: bool = True,
    progress: ProgressFn | None = _default_progress,
) -> list[StoredCase]:
    """Backfill exonerations from **offline CourtListener bulk snapshots**.

    The matched twin of :func:`backfill_store` that never touches the API: it
    joins each exoneration to an ``opinion-clusters`` snapshot by name+year (same
    scorer as the live flow) and attaches ``plain_text`` from the ``opinions``
    snapshot for matches only. Because there is no per-record request, the whole
    set is linked in two streaming passes rather than thousands of throttled
    calls. Persistence and resume semantics match :func:`backfill_store`: rows are
    rewritten after every record (atomic), already-matched rows are kept and
    skipped, and existing gap rows are retried in case the snapshot now links them.
    A match here means exactly what an API match means — both assemble through
    :func:`risk_engine.dataset.labeled_example_from_candidate`.
    """
    from .acquisition import BulkCourtListenerMatcher
    from .dataset import criteria_from_exoneration, labeled_example_from_candidate
    from .retrieval import surname_token

    records = list(records)
    total = len(records)
    path = Path(path)
    by_id: dict[str, StoredCase] = (
        {case.nre_id: case for case in load_cases(path)} if resume else {}
    )

    def _key(done: int, record: ExonerationRecord) -> str:
        return record.nre_id or f"_row_{done}"

    # Work only the records still needing a match (skip already-matched rows), so
    # the surname index and the opinion-text pass stay bounded to what is pending.
    pending = [
        (key, record)
        for done, record in enumerate(records, 1)
        if (key := _key(done, record)) and not (by_id.get(key) and by_id[key].matched)
    ]

    matcher = BulkCourtListenerMatcher(clusters_path, opinions_path=opinions_path)
    print(f"[bulk] indexing clusters for {len(pending)} pending records", file=sys.stderr, flush=True)
    matcher.build_index(surname_token(record.name) for _, record in pending)

    matches: dict[str, object] = {}
    cases_by_cluster: dict[str, object] = {}
    for key, record in pending:
        candidate = matcher.best_match(criteria_from_exoneration(record))
        matches[key] = candidate
        if candidate is not None:
            cluster_id = candidate.case.features["_cl_cluster_id"]
            cases_by_cluster[cluster_id] = candidate.case
    # The surname index (potentially ~1 GB) is no longer needed; free it before
    # the memory-heavy opinion-text pass so a small box keeps headroom.
    matcher._index.clear()
    print(
        f"[bulk] matched {len(cases_by_cluster)} clusters; resolving opinion text",
        file=sys.stderr,
        flush=True,
    )
    matcher.attach_text(cases_by_cluster)  # type: ignore[arg-type]
    print("[bulk] text resolved; writing case store", file=sys.stderr, flush=True)

    for done, record in enumerate(records, 1):
        key = _key(done, record)
        prior = by_id.get(key)
        if prior is not None and prior.matched:
            if progress is not None:
                progress(done, total, "cached", prior)
            continue
        case = stored_from_example(
            labeled_example_from_candidate(record, matches.get(key), pipeline=pipeline)  # type: ignore[arg-type]
        )
        by_id[key] = case
        save_cases(by_id.values(), path)
        if progress is not None:
            progress(done, total, "matched" if case.matched else "gap", case)
    return list(by_id.values())


@dataclass(frozen=True)
class CategoryAgreement:
    """Per-category flag-vs-label agreement over *matched* cases only (§6.6)."""

    category: str
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def fired(self) -> int:
        return self.true_positive + self.false_positive

    @property
    def support(self) -> int:
        return self.true_positive + self.false_negative

    @property
    def precision(self) -> float | None:
        return self.true_positive / self.fired if self.fired else None

    @property
    def recall(self) -> float | None:
        return self.true_positive / self.support if self.support else None

    @property
    def thin(self) -> bool:
        return self.support < THIN_SUPPORT


class CaseStore:
    """Searchable, analyzable view over the backfilled exoneration cases.

    A thin in-memory query layer (load the JSONL, filter/aggregate). Nothing here
    ranks or scores a case: :meth:`filtered` returns cases in stored order and
    analytics aggregate one dimension across cases (descriptive only).
    """

    def __init__(self, cases: list[StoredCase] | None = None):
        self.cases = list(cases or [])

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CASE_STORE_PATH) -> "CaseStore":
        store = cls(load_cases(path))
        # Best-effort overlay: tag Innocence Project cases from the shipped
        # roster. No-ops (leaves every flag False) when the roster is absent.
        tag_cases(store.cases)
        return store

    def __len__(self) -> int:
        return len(self.cases)

    def get(self, nre_id: str) -> StoredCase | None:
        """Return the single case with this ``nre_id``, or ``None`` if absent."""
        for case in self.cases:
            if case.nre_id == nre_id:
                return case
        return None

    def filtered(
        self,
        *,
        query: str | None = None,
        state: str | None = None,
        factor: str | None = None,
        matched: bool | None = None,
        innocence_project: bool | None = None,
    ) -> list[StoredCase]:
        """Return cases matching all supplied filters, in stored order.

        ``query`` matches the applicant name (case-insensitive substring),
        ``state`` matches exactly (case-insensitive), ``factor`` matches a labels
        or unmapped-factor value, ``matched`` filters gap vs matched, and
        ``innocence_project`` filters IP-secured vs other exonerations.
        """
        out = self.cases
        if query:
            needle = query.lower()
            out = [c for c in out if needle in c.name.lower()]
        if state:
            out = [c for c in out if c.state.lower() == state.lower()]
        if factor:
            out = [c for c in out if factor in c.labels or factor in c.unmapped_factors]
        if matched is not None:
            out = [c for c in out if c.matched is matched]
        if innocence_project is not None:
            out = [c for c in out if c.innocence_project is innocence_project]
        return out

    @property
    def matched_count(self) -> int:
        return sum(1 for c in self.cases if c.matched)

    @property
    def gap_count(self) -> int:
        return sum(1 for c in self.cases if not c.matched)

    @property
    def innocence_project_count(self) -> int:
        return sum(1 for c in self.cases if c.innocence_project)

    def states(self) -> list[str]:
        return sorted({c.state for c in self.cases if c.state})

    def factors(self) -> list[str]:
        seen: set[str] = set()
        for c in self.cases:
            seen.update(c.labels)
            seen.update(c.unmapped_factors)
        return sorted(seen)

    def by_state(self) -> list[tuple[str, int]]:
        counter = Counter(c.state for c in self.cases if c.state)
        return counter.most_common()

    def by_category(self) -> list[tuple[str, int]]:
        """Exoneration counts per NRE ground-truth category (descriptive)."""
        counter: Counter[str] = Counter()
        for c in self.cases:
            counter.update(c.labels)
        return counter.most_common()

    def by_unmapped_factor(self) -> list[tuple[str, int]]:
        """Counts of NRE blind-spot factors the engine cannot check (§6.5)."""
        counter: Counter[str] = Counter()
        for c in self.cases:
            counter.update(c.unmapped_factors)
        return counter.most_common()

    def agreement(self) -> list[CategoryAgreement]:
        """Per-category flag-vs-label agreement over matched cases (gaps excluded).

        This is the same per-element view calibration learns, surfaced for
        browsing: for each category it counts, across *matched* cases only, how
        often a fired flag was a true NRE factor. It never combines categories or
        cases into a single number.
        """
        tp: Counter[str] = Counter()
        fp: Counter[str] = Counter()
        fn: Counter[str] = Counter()
        categories = {c.value for c in FlagCategory}
        for case in self.cases:
            if not case.matched:
                continue
            labels = set(case.labels)
            predicted = set(case.predicted)
            for category in categories:
                in_pred = category in predicted
                in_actual = category in labels
                if in_pred and in_actual:
                    tp[category] += 1
                elif in_pred:
                    fp[category] += 1
                elif in_actual:
                    fn[category] += 1
        out = [
            CategoryAgreement(
                category=category,
                true_positive=tp[category],
                false_positive=fp[category],
                false_negative=fn[category],
            )
            for category in categories
        ]
        # Only categories that ever fired or had support are interesting.
        out = [a for a in out if a.fired or a.support]
        out.sort(key=lambda a: a.category)
        return out

    def confidence_table(self) -> dict[str, float]:
        """Per-element calibrated confidence keyed by FlagCategory value.

        A category's confidence is its precision over matched cases (the share of
        fired flags that were true NRE factors) — the same quantity the live
        calibration run computes, derived here from the already-persisted store so
        no second CourtListener pass is needed. Categories that never fired are
        omitted (no evidence to calibrate from). Still strictly per element: this
        is a dict of independent confidences, never a case-level composite (§3.1).
        """
        return {
            a.category: a.precision
            for a in self.agreement()
            if a.precision is not None
        }
