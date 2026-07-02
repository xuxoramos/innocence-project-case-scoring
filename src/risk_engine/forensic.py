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


#: What each discreditation tier means (spec v3 §3.4, point 4 / Appendix A). The
#: tier is a per-element descriptor grounded in a named citing authority, never a
#: numeric score: Tier A methods have been formally invalidated or abandoned,
#: Tier B methods are unvalidated per NAS 2009 / PCAST 2016 but still in use, and
#: Tier C methods are contested or evolving in the literature.
TIER_MEANING: dict[str, str] = {
    "A": "formally invalidated or abandoned",
    "B": "unvalidated per NAS 2009 / PCAST 2016 but still in use",
    "C": "contested or evolving in the literature",
}


#: Curated reference table. Citations point at the case-independent scientific
#: record (NAS 2009 / PCAST 2016 and a few discipline-specific sources).
FORENSIC_METHOD_REFERENCE: tuple[ForensicMethodRef, ...] = (
    ForensicMethodRef(
        method="bite-mark comparison",
        status="discredited",
        source=(
            "PCAST 2016 found bitemark analysis not scientifically valid and "
            "unlikely to be salvageable; NAS 2009 Ch. 5 found no scientific basis "
            "for identifying a source from bitemarks."
        ),
        confidence=0.9,
        tier="A",
        authority="Texas Forensic Science Commission moratorium recommendation (2016); NAS 2009",
        aliases=("bite-mark", "bite mark", "bitemark", "odontology comparison"),
    ),
    ForensicMethodRef(
        method="microscopic hair comparison",
        status="discredited",
        source=(
            "NAS 2009 Ch. 5: no scientific basis for individualization by hair "
            "microscopy; FBI/DOJ 2015 review acknowledged flawed microscopic-hair "
            "testimony in the overwhelming majority of audited trials."
        ),
        confidence=0.9,
        tier="A",
        authority="FBI/DOJ microscopic-hair review (2015); NAS 2009",
        aliases=("hair microscopy", "microscopic hair", "hair comparison microscopy"),
    ),
    ForensicMethodRef(
        method="comparative bullet-lead analysis",
        status="discredited",
        source=(
            "NAS 2004 'Forensic Analysis: Weighing Bullet Lead Evidence' rejected "
            "the supporting inferences; the FBI discontinued the technique in 2005."
        ),
        confidence=0.9,
        tier="A",
        authority="FBI abandonment of the technique (2005); NAS 2004",
        aliases=("comparative bullet-lead", "bullet lead analysis", "CBLA"),
    ),
    ForensicMethodRef(
        method="arson burn-indicator analysis",
        status="discredited",
        source=(
            "Pre-NFPA-921 fire 'pour pattern' / burn-indicator folklore (crazed "
            "glass, alligatoring, low burn) was invalidated as a basis for "
            "determining incendiary origin; NFPA 921 (1992 onward) is the "
            "accepted standard."
        ),
        confidence=0.85,
        tier="C",
        authority="NFPA 921 fire-investigation standard",
        aliases=("pour pattern", "burn indicator", "alligatoring", "crazed glass"),
    ),
    ForensicMethodRef(
        method="shaken baby syndrome triad",
        status="scientifically contested",
        source=(
            "The diagnostic 'triad' as sole proof of abusive head trauma is "
            "contested in the biomechanical and medical literature; courts and "
            "reviews have flagged it as not scientifically settled."
        ),
        confidence=0.8,
        tier="C",
        authority="Contested biomechanical and medical literature",
        aliases=("shaken baby", "abusive head trauma triad"),
    ),
    ForensicMethodRef(
        method="firearm/toolmark identification",
        status="scientifically limited",
        source=(
            "PCAST 2016 found firearms/toolmark identification had not been "
            "established as foundationally valid and rested on a single "
            "appropriately-designed study with a non-trivial error rate."
        ),
        confidence=0.7,
        tier="B",
        authority="PCAST 2016; NAS 2009",
        aliases=("toolmark identification", "firearm identification", "ballistic match"),
    ),
    ForensicMethodRef(
        method="footwear / tire impression comparison",
        status="scientifically limited",
        source=(
            "PCAST 2016 found footwear/impression source-identification claims "
            "lacked established foundational validity for individualization."
        ),
        confidence=0.7,
        tier="B",
        authority="PCAST 2016",
        aliases=("footwear impression", "shoe print comparison", "tire impression"),
    ),
    ForensicMethodRef(
        method="complex DNA mixture interpretation",
        status="scientifically limited",
        source=(
            "PCAST 2016 found interpretation of complex DNA mixtures (multiple "
            "contributors, low template) foundationally valid only within narrow, "
            "validated bounds, and unreliable outside them."
        ),
        confidence=0.65,
        tier="B",
        authority="PCAST 2016",
        aliases=("complex dna mixture", "mixed dna interpretation", "low template dna"),
    ),
    ForensicMethodRef(
        method="bloodstain pattern analysis",
        status="scientifically contested",
        source=(
            "NAS 2009 Ch. 5 found bloodstain-pattern analysis opinions more "
            "subjective than scientific and the uncertainties not well understood."
        ),
        confidence=0.7,
        tier="C",
        authority="NAS 2009",
        aliases=("bloodstain pattern", "blood spatter analysis", "blood-spatter"),
    ),
    ForensicMethodRef(
        method="dog-scent identification",
        status="scientifically contested",
        source=(
            "Scent-lineup / dog-scent identification has repeatedly figured in "
            "documented wrongful-conviction casework and lacks validated error "
            "rates (Innocence Project casework)."
        ),
        confidence=0.7,
        tier="C",
        authority="Innocence Project casework",
        aliases=("scent lineup", "dog scent", "scent identification"),
    ),
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
