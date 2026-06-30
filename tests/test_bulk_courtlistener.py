"""Offline tests for the CourtListener bulk-data matcher (no network).

Every test feeds the matcher tiny in-memory CSV snapshots, so the whole
exoneration -> cluster -> text -> stored-case chain is exercised without an API
or a rate limit. A bulk match must mean the same thing an API match means, so we
assert it lands on the same name+year scorer and assembles the same labeled rows.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from risk_engine.acquisition.bulk_courtlistener import (
    BulkCourtListenerMatcher,
    ClusterRecord,
    iter_cluster_records,
    resolve_latest_snapshot,
)
from risk_engine.labels import ExonerationRecord
from risk_engine.models import FlagCategory
from risk_engine.retrieval import MatchCriteria
from risk_engine.store import backfill_store_bulk, load_cases

_CLUSTERS = (
    "id,case_name,case_name_full,case_name_short,date_filed,docket_id\n"
    'C1,"Commonwealth v. Doswell, Jr.",,,1986-05-01,D1\n'
    "C2,People v. Smith,,,1990-02-02,D2\n"
    "C3,Commonwealth v. Doswell,,,2015-01-01,D3\n"  # same surname, wrong year
)

_OPINIONS = (
    "id,plain_text,html,cluster_id\n"
    'O1,"The conviction rested on bite-mark comparison evidence at trial.",,C1\n'
    'O2,"An ordinary appeal with nothing notable.",,C2\n'
)


def _write(path: Path, text: str, *, gz: bool = False) -> Path:
    if gz:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
            fh.write(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _record(**overrides) -> ExonerationRecord:
    return ExonerationRecord(
        nre_id=overrides.get("nre_id", "NRE-1"),
        name=overrides.get("name", "Thomas Doswell"),
        state=overrides.get("state", "Pennsylvania"),
        county=overrides.get("county", "Allegheny"),
        crime=overrides.get("crime", "Sexual Assault"),
        crime_year=overrides.get("crime_year", 1986),
        conviction_year=overrides.get("conviction_year", 1986),
        factors=overrides.get(
            "factors",
            {"False or Misleading Forensic Evidence", "Official Misconduct"},
        ),
    )


def test_iter_cluster_records_parses_name_year_and_quoting(tmp_path):
    rows = list(iter_cluster_records(_write(tmp_path / "clusters.csv", _CLUSTERS)))
    by_id = {r.cluster_id: r for r in rows}
    # Quoted caption with an embedded comma stays intact; year comes from date_filed.
    assert by_id["C1"].case_name == "Commonwealth v. Doswell, Jr."
    assert by_id["C1"].year == 1986
    assert by_id["C3"].year == 2015


def test_iter_cluster_records_reads_gzip(tmp_path):
    path = _write(tmp_path / "clusters.csv.gz", _CLUSTERS, gz=True)
    rows = list(iter_cluster_records(path))
    assert {r.cluster_id for r in rows} == {"C1", "C2", "C3"}


def test_iter_cluster_records_handles_fields_over_default_csv_limit(tmp_path):
    # Real snapshots carry opinion/cluster text fields far larger than Python's
    # default 128 KB per-field cap; the reader must not die on them.
    huge = "x" * 200_000
    csv_text = (
        "id,case_name,case_name_full,case_name_short,date_filed,docket_id\n"
        f'C9,Commonwealth v. Big,"{huge}",,1999-01-01,D9\n'
    )
    rows = list(iter_cluster_records(_write(tmp_path / "big.csv", csv_text)))
    assert len(rows) == 1
    assert rows[0].cluster_id == "C9" and rows[0].year == 1999


def test_build_index_is_bounded_to_relevant_surnames(tmp_path):
    matcher = BulkCourtListenerMatcher(_write(tmp_path / "clusters.csv", _CLUSTERS))
    matcher.build_index(["doswell"])
    # Only the exoneree's surname is indexed; the unrelated 'Smith' cluster is dropped.
    assert set(matcher._index) == {"doswell"}
    assert {r.cluster_id for r in matcher._index["doswell"]} == {"C1", "C3"}


def test_best_match_uses_name_and_year_scorer(tmp_path):
    matcher = BulkCourtListenerMatcher(_write(tmp_path / "clusters.csv", _CLUSTERS))
    matcher.build_index(["doswell"])
    match = matcher.best_match(MatchCriteria("Thomas Doswell", 1986))
    assert match is not None and match.is_match
    # 1986 picks the contemporaneous cluster over the same-surname 2015 one.
    assert match.case.features["_cl_cluster_id"] == "C1"


def test_best_match_returns_none_for_absent_surname(tmp_path):
    matcher = BulkCourtListenerMatcher(_write(tmp_path / "clusters.csv", _CLUSTERS))
    matcher.build_index(["nobody"])
    assert matcher.best_match(MatchCriteria("Zelda Nobody", 1986)) is None


def test_attach_text_fills_documents_for_matched_clusters_only(tmp_path):
    matcher = BulkCourtListenerMatcher(
        _write(tmp_path / "clusters.csv", _CLUSTERS),
        opinions_path=_write(tmp_path / "opinions.csv", _OPINIONS),
    )
    case = ClusterRecord("C1", "Commonwealth v. Doswell", 1986).to_case()
    attached = matcher.attach_text({"C1": case})
    assert attached == 1
    assert case.documents and "bite-mark" in case.documents[0].normalized_text
    assert case.documents[0].needs_ocr is False


def test_backfill_store_bulk_end_to_end_and_resume(tmp_path):
    clusters = _write(tmp_path / "clusters.csv", _CLUSTERS)
    opinions = _write(tmp_path / "opinions.csv", _OPINIONS)
    store = tmp_path / "case_store.jsonl"
    records = [_record(), _record(nre_id="NRE-2", name="Zelda Nobody")]

    cases = backfill_store_bulk(
        records,
        clusters_path=clusters,
        opinions_path=opinions,
        path=store,
        progress=None,
    )
    by_id = {c.nre_id: c for c in cases}
    # The Doswell exoneration links its 1986 opinion and the pipeline flags it.
    assert by_id["NRE-1"].matched is True
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD.value in by_id["NRE-1"].predicted
    # The NRE ground-truth label is carried regardless of what the pipeline found.
    assert FlagCategory.DISCREDITED_FORENSIC_METHOD.value in by_id["NRE-1"].labels
    # The unmatched surname is a gap: labels but no predictions (§6.6).
    assert by_id["NRE-2"].matched is False
    assert by_id["NRE-2"].predicted == []

    # Resuming keeps the matched row untouched and does not re-link it.
    again = backfill_store_bulk(
        records,
        clusters_path=clusters,
        opinions_path=opinions,
        path=store,
        progress=None,
    )
    assert {c.nre_id for c in again} == {"NRE-1", "NRE-2"}
    assert load_cases(store) == again


def test_resolve_latest_snapshot_picks_newest_dated_file(tmp_path):
    (tmp_path / "opinion-clusters-2026-03-31.csv").write_text("", encoding="utf-8")
    newest = tmp_path / "opinion-clusters-2026-06-30.csv"
    newest.write_text("", encoding="utf-8")
    (tmp_path / "ignore-me.csv").write_text("", encoding="utf-8")
    assert resolve_latest_snapshot(tmp_path, "opinion-clusters") == newest
    assert resolve_latest_snapshot(tmp_path, "opinions") is None
