"""Command-line entry point.

Three subcommands:

    risk-engine intake --intake path/to/intake.json --intake-source allegheny_pa
    risk-engine calibrate --state Pennsylvania --max-records 100
    risk-engine backfill --state Pennsylvania --max-records 100

``intake`` is the single front door (README v2 Section 5): intake -> structured
record -> matching public records -> element-level flags -> case packet. There
is no archive scanning and no ranking (Section 4 puts candidate scanning out of
scope). The output is a flat, unranked packet: each case is shown with the
elements that matched a documented category of concern, the absence of a flag
never implies the absence of a problem, and a missing record (gap) is never
conflated with a clean one (Section 6.6 / Section 7).

``calibrate`` is the throwaway step-4 batch job: it links NRE exonerations to
their court records and learns a per-element confidence table (it never produces
a case-level score). Run it on demand after changing the detectors, not on a
schedule. The ``intake`` flow automatically applies the learned table when one
exists, and behaves identically to the raw pipeline when it does not.

``backfill`` populates the browse/analytics store: it turns confirmed NRE
exonerations into the same intake schema and persists them (with their NRE
ground-truth factors and, when ``--match`` links a court record, the engine's
flags). With ``--no-match`` it is fully offline and writes gap rows (labels but
no predictions). These are confirmed exonerations only, never scored or ranked.
"""

from __future__ import annotations

import argparse
import json
import sys

from .acquisition import (
    DEFAULT_BULK_DIR,
    download_bulk_snapshots,
    list_sources,
    resolve_latest_snapshot,
)
from .acquisition.bulk_courtlistener import CLUSTERS_STEM, OPINIONS_STEM
from .calibration import (
    DEFAULT_CALIBRATION_PATH,
    calibrated_pipeline,
    format_report,
    run_calibration,
    save_calibration,
)
from .intake.structuring import structure_intake
from .labels import load_known_exonerations
from .models import FlagCategory
from .retrieval import build_packet_for_intake
from .store import DEFAULT_CASE_STORE_PATH, CaseStore, backfill_store, backfill_store_bulk


def run_intake(
    intake_path: str,
    *,
    source_key: str,
    ocr: bool,
    text: bool,
    tabular: bool,
    limit: int | None,
) -> str:
    """Process one intake questionnaire end to end into a rendered packet."""
    with open(intake_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    # Accept either a flat {label: value} object or a wrapper with metadata.
    if isinstance(payload.get("fields"), dict):
        raw_fields = payload["fields"]
        chapter = payload.get("chapter", "PA")
        applicant_ref = payload.get("applicant_ref", "")
    else:
        raw_fields = payload
        chapter = "PA"
        applicant_ref = ""
    intake = structure_intake(raw_fields, chapter=chapter, applicant_ref=applicant_ref)
    # Apply learned per-element confidences when a calibration table exists; this
    # is a no-op (identical to default_pipeline) when none has been produced yet.
    pipeline = calibrated_pipeline(ocr=ocr, text=text, tabular=tabular)
    packet = build_packet_for_intake(
        intake, source_key=source_key, pipeline=pipeline, limit=limit
    )
    return packet.render_text()


def run_calibrate(
    *,
    source_key: str,
    state: str | None,
    county: str | None,
    max_records: int | None,
    match_limit: int,
    out: str | None,
    save: bool,
    from_store: bool = False,
    store_path: str = str(DEFAULT_CASE_STORE_PATH),
) -> str:
    """Produce the per-element calibration table.

    The default path runs the live step-4 batch (one CourtListener pass). With
    ``from_store=True`` the table is derived from the already-persisted case store
    instead — no network — reusing whatever matched cases a resumable ``backfill``
    linked. Either way the result is a dict of independent per-element
    confidences, never a case composite (§3.1).
    """
    if from_store:
        store = CaseStore.load(store_path)
        confidences = {
            FlagCategory(value): conf for value, conf in store.confidence_table().items()
        }
        if save:
            save_calibration(confidences, out or DEFAULT_CALIBRATION_PATH)
        return _format_store_calibration(store)
    kwargs = {} if out is None else {"save_path": out}
    report = run_calibration(
        source_key=source_key,
        state=state,
        county=county,
        max_records=max_records,
        match_limit=match_limit,
        save=save,
        **kwargs,
    )
    return format_report(report)


def _format_store_calibration(store: CaseStore) -> str:
    """Render the store-derived calibration as the same honest per-element table."""
    rows = store.agreement()
    lines = [
        f"Calibration from store: {store.matched_count} matched case(s), "
        f"{store.gap_count} gap(s) excluded (retrieval gaps, not misses).",
        "",
        f"{'category':<28}{'fired':>7}{'support':>9}{'precision':>11}  notes",
    ]
    for a in rows:
        precision = "n/a" if a.precision is None else f"{a.precision:.2f}"
        notes = "thin support" if a.thin else ""
        lines.append(
            f"{a.category:<28}{a.fired:>7}{a.support:>9}{precision:>11}  {notes}"
        )
    if not rows:
        lines.append("(no matched cases in the store yet — run `backfill` without --no-match)")
    return "\n".join(lines)


def run_backfill(
    *,
    source_key: str,
    state: str | None,
    county: str | None,
    max_records: int | None,
    match_limit: int,
    match: bool,
    out: str,
    resume: bool,
    bulk: bool = False,
    bulk_dir: str | None = None,
    bulk_clusters: str | None = None,
    bulk_opinions: str | None = None,
) -> str:
    """Backfill confirmed exonerations into the browse store and report counts.

    Persists after every record and (with ``resume``) skips cases already linked,
    so a killed run resumes where it left off. With ``--bulk`` the court-record
    link comes from offline CourtListener snapshots (no API, no rate limit)
    instead of per-record lookups. Per-record progress is logged to stderr; this
    summary line goes to stdout.
    """
    records = load_known_exonerations(state=state, county=county)
    if max_records is not None:
        records = records[:max_records]
    if bulk:
        clusters_path, opinions_path = _resolve_bulk_paths(
            bulk_dir, bulk_clusters, bulk_opinions
        )
        cases = backfill_store_bulk(
            records,
            clusters_path=clusters_path,
            opinions_path=opinions_path,
            path=out,
            resume=resume,
        )
    else:
        cases = backfill_store(
            records,
            path=out,
            match=match,
            source_key=source_key,
            match_limit=match_limit,
            resume=resume,
        )
    matched = sum(1 for c in cases if c.matched)
    gaps = len(cases) - matched
    return (
        f"Store now holds {len(cases)} confirmed exoneration(s) at {out}: "
        f"{matched} matched to a court record, {gaps} gap(s) "
        f"(no matching record; §6.6 — not a detector miss)."
    )


def _resolve_bulk_paths(
    bulk_dir: str | None,
    bulk_clusters: str | None,
    bulk_opinions: str | None,
) -> tuple[str, str | None]:
    """Locate the cluster (required) and opinion (optional) snapshots for --bulk.

    Explicit ``--bulk-clusters/--bulk-opinions`` win; otherwise the newest dated
    snapshot in ``--bulk-dir`` is used. A missing cluster snapshot is a hard error
    pointing at ``bulk-download``.
    """
    directory = bulk_dir or str(DEFAULT_BULK_DIR)
    clusters = bulk_clusters or (
        str(p) if (p := resolve_latest_snapshot(directory, CLUSTERS_STEM)) else None
    )
    if clusters is None:
        raise SystemExit(
            f"No '{CLUSTERS_STEM}-*' snapshot found in {directory}. "
            "Fetch one first:  risk-engine bulk-download --dir " + directory
        )
    opinions = bulk_opinions or (
        str(p) if (p := resolve_latest_snapshot(directory, OPINIONS_STEM)) else None
    )
    return clusters, opinions


def run_bulk_download(directory: str) -> str:
    """Download the latest CourtListener bulk snapshots used by --bulk."""
    paths = download_bulk_snapshots(directory, progress=lambda m: print(m, file=sys.stderr))
    listing = ", ".join(f"{stem}={path.name}" for stem, path in paths.items())
    return f"Downloaded bulk snapshots into {directory}: {listing}"



def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Wrongful-conviction intake flagging POC")
    sub = p.add_subparsers(dest="command", required=True)

    intake = sub.add_parser("intake", help="process one intake questionnaire into a case packet")
    intake.add_argument("--intake", metavar="PATH", required=True, help="intake questionnaire JSON")
    intake.add_argument(
        "--intake-source",
        default="allegheny_pa",
        help=f"acquisition source to retrieve records from (one of {list_sources()})",
    )
    intake.add_argument("--limit", type=int, default=None)
    intake.add_argument("--no-ocr", dest="ocr", action="store_false")
    intake.add_argument("--no-text", dest="text", action="store_false")
    intake.add_argument("--no-tabular", dest="tabular", action="store_false")

    cal = sub.add_parser("calibrate", help="run the step-4 calibration batch (writes a table)")
    cal.add_argument("--source", default="appellate_cl", help="acquisition source for record lookups")
    cal.add_argument("--state", default=None, help="limit the NRE reference subset to a state")
    cal.add_argument("--county", default=None, help="limit the NRE reference subset to a county")
    cal.add_argument("--max-records", type=int, default=None, help="cap the number of live lookups")
    cal.add_argument("--match-limit", type=int, default=50, help="candidates considered per record")
    cal.add_argument("--out", default=None, help="where to write the calibration table (JSON)")
    cal.add_argument("--no-save", dest="save", action="store_false", help="evaluate without writing")
    cal.add_argument(
        "--from-store",
        dest="from_store",
        action="store_true",
        help="derive the table from the persisted case store instead of querying (no network)",
    )
    cal.add_argument(
        "--store",
        dest="store_path",
        default=str(DEFAULT_CASE_STORE_PATH),
        help="case store to derive from when --from-store is set",
    )

    bf = sub.add_parser("backfill", help="populate the browse/analytics case store from exonerations")
    bf.add_argument("--source", default="appellate_cl", help="acquisition source for record lookups")
    bf.add_argument("--state", default=None, help="limit the NRE reference subset to a state")
    bf.add_argument("--county", default=None, help="limit the NRE reference subset to a county")
    bf.add_argument("--max-records", type=int, default=None, help="cap the number of cases")
    bf.add_argument("--match-limit", type=int, default=50, help="candidates considered per record")
    bf.add_argument(
        "--no-match",
        dest="match",
        action="store_false",
        help="offline: back-fill labels only, no court-record lookup (writes gap rows)",
    )
    bf.add_argument(
        "--out",
        default=str(DEFAULT_CASE_STORE_PATH),
        help="where to write the case store (JSON Lines)",
    )
    bf.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="reprocess every record instead of skipping cases already in the store",
    )
    bf.add_argument(
        "--bulk",
        action="store_true",
        help="link court records from offline CourtListener bulk snapshots (no API/rate limit)",
    )
    bf.add_argument(
        "--bulk-dir",
        default=None,
        help=f"directory holding bulk snapshots (default {DEFAULT_BULK_DIR})",
    )
    bf.add_argument(
        "--bulk-clusters",
        default=None,
        help="explicit opinion-clusters snapshot (overrides --bulk-dir lookup)",
    )
    bf.add_argument(
        "--bulk-opinions",
        default=None,
        help="explicit opinions snapshot for text (overrides --bulk-dir lookup)",
    )

    dl = sub.add_parser("bulk-download", help="download the latest CourtListener bulk snapshots")
    dl.add_argument(
        "--dir",
        dest="bulk_dir",
        default=str(DEFAULT_BULK_DIR),
        help=f"where to store snapshots (default {DEFAULT_BULK_DIR})",
    )

    args = p.parse_args(argv)
    if args.command == "intake":
        print(
            run_intake(
                args.intake,
                source_key=args.intake_source,
                ocr=args.ocr,
                text=args.text,
                tabular=args.tabular,
                limit=args.limit,
            )
        )
    elif args.command == "calibrate":
        print(
            run_calibrate(
                source_key=args.source,
                state=args.state,
                county=args.county,
                max_records=args.max_records,
                match_limit=args.match_limit,
                out=args.out,
                save=args.save,
                from_store=args.from_store,
                store_path=args.store_path,
            )
        )
    elif args.command == "backfill":
        print(
            run_backfill(
                source_key=args.source,
                state=args.state,
                county=args.county,
                max_records=args.max_records,
                match_limit=args.match_limit,
                match=args.match,
                out=args.out,
                resume=args.resume,
                bulk=args.bulk,
                bulk_dir=args.bulk_dir,
                bulk_clusters=args.bulk_clusters,
                bulk_opinions=args.bulk_opinions,
            )
        )
    elif args.command == "bulk-download":
        print(run_bulk_download(args.bulk_dir))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
