"""Curated recall fixture + softened recall gate (spec v3 §10, items 16 & 17).

Runs the flagging pipeline over a curated set of short, synthetic opinion
snippets with ground-truth expected categories, prints a per-category confusion
matrix (precision / recall), and **enforces one hard gate**: 100% recall for the
discredited-forensic-method flag across the known-forensic cases. Real-world
recall on other categories is reported, never a hard merge blocker — the
consultant's 100% gate is scoped to the curated forensic set (item 16), keeping
the sensitivity-over-precision posture without an unattainable global bar.
"""

from __future__ import annotations

import json
from pathlib import Path

from risk_engine.models import Case, Document, FlagCategory
from risk_engine.processing import default_pipeline

_FIXTURE = Path(__file__).resolve().parent / "data" / "recall_fixture.json"
_FORENSIC = FlagCategory.DISCREDITED_FORENSIC_METHOD.value


def _predict(text: str) -> set[str]:
    case = Case(case_id="R", jurisdiction="j")
    case.documents.append(Document(doc_id="R1", case_id="R", needs_ocr=False, normalized_text=text))
    return {f.category.value for f in default_pipeline(ocr=False).process(case).flags}


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["cases"]


def _confusion() -> dict[str, dict[str, int]]:
    """Per-category TP/FP/FN over the whole fixture."""
    stats: dict[str, dict[str, int]] = {}

    def bump(cat: str, key: str) -> None:
        stats.setdefault(cat, {"tp": 0, "fp": 0, "fn": 0})[key] += 1

    for case in _load_cases():
        expected = set(case["expect"])
        predicted = _predict(case["text"])
        for cat in expected | predicted:
            if cat in expected and cat in predicted:
                bump(cat, "tp")
            elif cat in predicted:
                bump(cat, "fp")
            else:
                bump(cat, "fn")
    return stats


def test_forensic_recall_gate_is_100_percent(capsys):
    """Hard gate (item 16): every known-forensic case fires the forensic flag."""
    cases = _load_cases()
    misses = [
        c["id"]
        for c in cases
        if _FORENSIC in set(c["expect"]) and _FORENSIC not in _predict(c["text"])
    ]
    assert not misses, f"forensic recall < 100% — missed: {misses}"


def test_confusion_matrix_report(capsys):
    """Report (item 17): print the per-category confusion matrix; never hard-fail
    on non-forensic recall (real-world recall is measured, not gated)."""
    stats = _confusion()
    lines = [f"{'category':<34}{'TP':>4}{'FP':>4}{'FN':>4}{'precision':>11}{'recall':>9}"]
    for cat in sorted(stats):
        s = stats[cat]
        fired = s["tp"] + s["fp"]
        support = s["tp"] + s["fn"]
        precision = (s["tp"] / fired) if fired else float("nan")
        recall = (s["tp"] / support) if support else float("nan")
        lines.append(
            f"{cat:<34}{s['tp']:>4}{s['fp']:>4}{s['fn']:>4}{precision:>11.2f}{recall:>9.2f}"
        )
    report = "\n".join(lines)
    with capsys.disabled():
        print("\n" + report)
    # Sanity only: the fixture ran and produced a matrix; forensic support is the
    # 10 curated forensic cases.
    assert stats[_FORENSIC]["tp"] + stats[_FORENSIC]["fn"] == 10


def test_clean_control_produces_no_flags():
    """The clean control case must not over-flag (precision guard)."""
    clean = next(c for c in _load_cases() if c["id"] == "C-clean")
    assert _predict(clean["text"]) == set()
