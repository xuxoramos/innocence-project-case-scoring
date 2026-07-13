"""Discredited / scientifically-limited forensic methods reference.

This is the independent verification source for the ``DISCREDITED_FORENSIC_METHOD``
flag (README v2 Section 5.2). The key property: every entry is grounded in a
case-independent scientific source — primarily the National Academy of Sciences
2009 report *Strengthening Forensic Science in the United States: A Path Forward*
and the 2016 President's Council of Advisors on Science and Technology (PCAST)
report *Forensic Science in Criminal Courts: Ensuring Scientific Validity of
Feature-Comparison Methods* — not a comparison to any defendant's guilt.

A flag fires only when a method named here appears in a case record; the cited
source travels with the flag so an attorney can verify the basis directly. This
file is a curated POC reference, not an exhaustive catalogue, and the citations
are deliberately specific so they can be checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexicons import load_junk_science


@dataclass(frozen=True)
class ForensicMethodRef:
    """One forensic method with its scientific status and independent source."""

    method: str  # canonical method name
    status: str  # e.g. "discredited", "scientifically limited"
    source: str  # specific, checkable citation independent of any case outcome
    confidence: float  # extraction confidence to assign when matched
    tier: str = ""  # discreditation tier: "A", "B", or "C" (see TIER_MEANING)
    authority: str = ""  # the body/report whose ruling places this method in its tier
    aliases: tuple[str, ...] = ()  # phrasings to match in case text

    @property
    def match_terms(self) -> tuple[str, ...]:
        return (self.method, *self.aliases)


#: Parsed ``lexicons/junk_science.json`` — the editable source of the reference
#: below and of ``TIER_MEANING``. Externalized (spec v3 §10, item 2) so terms,
#: tiers, and citations are a reviewable diff rather than hard-coded here.
_JUNK_SCIENCE = load_junk_science()


#: What each discreditation tier means (spec v3 §3.4, point 4 / Appendix A). The
#: tier is a per-element descriptor grounded in a named citing authority, never a
#: numeric score: Tier A methods have been formally invalidated or abandoned,
#: Tier B methods are unvalidated per NAS 2009 / PCAST 2016 but still in use, and
#: Tier C methods are contested or evolving in the literature.
TIER_MEANING: dict[str, str] = dict(_JUNK_SCIENCE["tier_meaning"])



#: Curated reference table, built from ``lexicons/junk_science.json``. Citations
#: point at the case-independent scientific record (NAS 2009 / PCAST 2016 and a
#: few discipline-specific sources). Edit the JSON, not this module, to change it.
FORENSIC_METHOD_REFERENCE: tuple[ForensicMethodRef, ...] = tuple(
    ForensicMethodRef(
        method=m["method"],
        status=m["status"],
        source=m["source"],
        confidence=m["confidence"],
        tier=m.get("tier", ""),
        authority=m.get("authority", ""),
        aliases=tuple(m.get("aliases", ())),
    )
    for m in _JUNK_SCIENCE["methods"]
)

# Word-boundary matchers for every term, paired back to their reference entry.
_COMPILED: tuple[tuple[re.Pattern[str], ForensicMethodRef], ...] = tuple(
    (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), ref)
    for ref in FORENSIC_METHOD_REFERENCE
    for term in ref.match_terms
)


@dataclass(frozen=True)
class ForensicMethodHit:
    """A reference entry matched in text, with the matched span."""

    ref: ForensicMethodRef
    start: int
    end: int


def find_forensic_methods(text: str) -> list[ForensicMethodHit]:
    """Find discredited/limited methods named in ``text`` (first hit per method)."""
    seen: set[str] = set()
    hits: list[ForensicMethodHit] = []
    for pattern, ref in _COMPILED:
        if ref.method in seen:
            continue
        match = pattern.search(text)
        if match is not None:
            seen.add(ref.method)
            hits.append(ForensicMethodHit(ref=ref, start=match.start(), end=match.end()))
    return hits
