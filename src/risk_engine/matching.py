"""Anchor + assertive-modifier + word-window matcher (spec v3 §10, item 1).

A generalization of the fixed multi-word phrases used by the keyword extractor.
A *windowed rule* fires when an **anchor** term (the core noun, e.g. ``informant``)
and an **assertive modifier** (e.g. ``testified`` / ``deal``) both appear within a
bounded number of words of each other. This lifts recall over rigid phrases,
without the noise of bare single tokens, because both halves must co-occur close
together — the design our corpus mining independently pointed to (paired
phrasings carry the signal; bare tokens are dominated by procedural noise).

Deterministic and dependency-free (regex tokenization + integer distance), so it
stays in keeping with the stdlib-only core.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A token is a run of alphanumerics, keeping internal hyphens/apostrophes so
#: ``co-defendant`` and ``witness's`` stay single tokens.
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


@dataclass(frozen=True)
class WindowRule:
    """One anchor+modifier+window rule with the confidence to assign on a hit.

    ``term`` is an optional identifier used downstream to look up a descriptor
    (e.g. a misconduct type); ``None`` when the rule carries no descriptor.
    """

    anchors: frozenset[str]
    modifiers: frozenset[str]
    window: int
    confidence: float
    term: str | None = None


def _tokens(text: str) -> list[tuple[str, int, int]]:
    """Lower-cased word tokens with their character spans."""
    return [(m.group(0).lower(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def find_windowed(
    text: str,
    anchors: frozenset[str],
    modifiers: frozenset[str],
    window: int,
) -> tuple[int, int] | None:
    """Return the character span of the first anchor that has a modifier nearby.

    Scans left to right; the first anchor token with any modifier token within
    ``window`` positions (and not the anchor itself) wins, and its character span
    is returned so callers can quote the surrounding sentence. ``None`` when no
    anchor and modifier co-occur within the window.
    """
    tokens = _tokens(text)
    if not tokens:
        return None
    modifier_positions = {i for i, (w, _, _) in enumerate(tokens) if w in modifiers}
    if not modifier_positions:
        return None
    for i, (word, start, end) in enumerate(tokens):
        if word not in anchors:
            continue
        lo, hi = i - window, i + window
        if any(lo <= j <= hi and j != i for j in modifier_positions):
            return (start, end)
    return None
