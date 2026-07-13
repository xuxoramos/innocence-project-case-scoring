"""Trial-defense-strategy note (spec v3 §10, consultant-review item 11, reframed).

The review proposed flagging a "defense strategy incompatibility" when the trial
defense was self-defense or consent (both concede that the act occurred, which
sits in tension with an actual-innocence claim). Adopted here **only** as a
neutral, checkable descriptive note — never a flag, never a viability score, and
never a "less likely innocent" signal (README v2 §3.1). It records an observable
fact about the record ("the trial defense was self-defense, which concedes the
act occurred") and leaves every judgment to the human reviewer.
"""

from __future__ import annotations

import re

#: Conceding trial-defense strategies and the neutral note each yields. Only the
#: strategies that *concede the act* are noted, because that is the observable
#: record fact the reviewer asked to see; the note asserts nothing about the
#: merits. Matched with word boundaries against the record text.
_STRATEGY_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "self-defense",
        re.compile(r"\bself[-\s]?defense\b", re.IGNORECASE),
        "Trial defense noted: self-defense, which concedes the act occurred. "
        "Descriptive record fact only — not a judgment of the case.",
    ),
    (
        "consent",
        re.compile(r"\b(consent defense|defense of consent|encounter was consensual|"
                   r"claimed .{0,20}consensual)\b", re.IGNORECASE),
        "Trial defense noted: consent, which concedes the act occurred. "
        "Descriptive record fact only — not a judgment of the case.",
    ),
)


def defense_strategy_note(text: str) -> str | None:
    """Return a neutral note if a conceding trial-defense strategy is stated.

    Returns ``None`` when no conceding strategy is found. The note is purely
    descriptive and never feeds any score or ranking (README v2 §3.1).
    """
    for _label, pattern, note in _STRATEGY_PATTERNS:
        if pattern.search(text or ""):
            return note
    return None
