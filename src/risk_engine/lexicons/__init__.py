"""Externalized detection lexicons (spec v3 §10, consultant-review item 2).

The term knowledge that drives flagging lives in editable JSON here, not hard-
coded in the processing modules, so a chapter or reviewer can adjust terms,
confidences, and citations as a plain reviewable diff:

* ``junk_science.json`` — the discredited/limited forensic-method reference
  (loaded by :mod:`risk_engine.forensic`).
* ``rules.json`` — the case-record circumstance & official-misconduct lexemes and
  the misconduct-type map (loaded by :mod:`risk_engine.processing.tabular`).

Paths resolve relative to this package, so loading is independent of the current
working directory.
"""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent

JUNK_SCIENCE_PATH = _DIR / "junk_science.json"
RULES_PATH = _DIR / "rules.json"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_junk_science() -> dict:
    """Parsed ``junk_science.json`` (keys: ``tier_meaning``, ``methods``)."""
    return _load(JUNK_SCIENCE_PATH)


def load_rules() -> dict:
    """Parsed ``rules.json`` (keys: ``lexemes``, ``misconduct_types``)."""
    return _load(RULES_PATH)


__all__ = ["load_junk_science", "load_rules", "JUNK_SCIENCE_PATH", "RULES_PATH"]
