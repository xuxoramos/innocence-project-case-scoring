"""Command-line entry point that wires the full pipeline together.

    risk-engine --jurisdiction allegheny_pa --scorer flag_count --no-ocr

Each processing step can be toggled independently so already-digitized cases
can skip OCR/text/tabular.
"""

from __future__ import annotations

import argparse

from .acquisition import get_source, list_sources
from .processing import default_pipeline
from .scoring import get_scorer, list_scorers


def run(jurisdiction: str, scorer: str, ocr: bool, text: bool, tabular: bool, limit: int | None):
    source = get_source(jurisdiction)
    pipeline = default_pipeline(ocr=ocr, text=text, tabular=tabular)
    cases = [pipeline.process(source.fetch(c)) for c in source.discover(limit=limit)]
    return get_scorer(scorer).rank(cases)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Wrongful-conviction case triage POC")
    p.add_argument("--jurisdiction", default="allegheny_pa", help=f"one of {list_sources()}")
    p.add_argument("--scorer", default="flag_count", help=f"one of {list_scorers()}")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-ocr", dest="ocr", action="store_false")
    p.add_argument("--no-text", dest="text", action="store_false")
    p.add_argument("--no-tabular", dest="tabular", action="store_false")
    args = p.parse_args(argv)
    worklist = run(args.jurisdiction, args.scorer, args.ocr, args.text, args.tabular, args.limit)
    for entry in worklist.entries:
        c = entry.case
        print(f"#{entry.rank} {c.case_id} ({c.year}) flags={len(c.flags)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
