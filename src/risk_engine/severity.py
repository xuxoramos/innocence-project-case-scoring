"""Case-seriousness descriptor (spec v3 §3.4, point 4 — the severity axis).

Grades the offense a case was convicted of into a seriousness tier so each
element flag can carry the *stakes of the case it sits in* as a labelled
descriptor. The grade rests on the offense class / typical custodial exposure —
homicide and death-eligible offenses carry the gravest exposure, then serious
violent felonies, other felonies, and lesser/misdemeanour offences — not on any
judgement of the particular case.

This corroborates the National Registry of Exonerations observation that
wrongful convictions concentrate in the most serious cases: in the project's own
4,311-case store, homicide-family offences (murder, manslaughter, attempted
murder, accessory to murder) account for roughly 44% of all exonerations, and
murder alone for 41%. The offence vocabulary below is the fixed NRE "Worst Crime
Display" taxonomy, so a stored case always grades exactly; a live applicant's
free-text offence is matched on the same whole-word keys, best effort.

The descriptor stays attached to the one element and is never combined with any
other descriptor or summed into a case-level number (README v2 §3.1). An offence
outside the known vocabulary carries no descriptor rather than a guessed grade
(§3.2).
"""

from __future__ import annotations

import re

#: Seriousness tier key -> human meaning (shown to the reviewer as the basis).
SERIOUSNESS_MEANING: dict[str, str] = {
    "capital": (
        "homicide or death-eligible offense — the gravest sentencing exposure "
        "(life or death)"
    ),
    "serious_violent": "serious violent felony — long custodial exposure",
    "felony": "other felony — significant custodial exposure",
    "lesser": "misdemeanor or lower-grade offense — limited custodial exposure",
}

#: Human label for each tier key, used as the descriptor value.
_TIER_LABEL: dict[str, str] = {
    "capital": "capital / homicide",
    "serious_violent": "serious violent felony",
    "felony": "felony",
    "lesser": "lesser / misdemeanor",
}

#: NRE "Worst Crime Display" offense (lower-cased) -> seriousness tier key.
#: Graded by offense class / sentencing exposure. Two NRE values are left out on
#: purpose because their grade is genuinely ambiguous — "Military Justice
#: Offense" and "Other" — so they yield no descriptor rather than a guess (§3.2).
_OFFENSE_TIER: dict[str, str] = {
    # Homicide / death-eligible.
    "murder": "capital",
    "manslaughter": "capital",
    "attempted murder": "capital",
    "accessory to murder": "capital",
    # Serious violent felonies.
    "sexual assault": "serious_violent",
    "child sex abuse": "serious_violent",
    "child abuse": "serious_violent",
    "dependent adult abuse": "serious_violent",
    "robbery": "serious_violent",
    "assault": "serious_violent",
    "kidnapping": "serious_violent",
    "arson": "serious_violent",
    "attempt, violent": "serious_violent",
    "other violent felony": "serious_violent",
    "supporting terrorism": "serious_violent",
    # Other felonies.
    "drug possession or sale": "felony",
    "weapon possession or sale": "felony",
    "fraud": "felony",
    "tax evasion/fraud": "felony",
    "other nonviolent felony": "felony",
    "burglary": "felony",
    "theft": "felony",
    "forgery": "felony",
    "conspiracy": "felony",
    "bribery": "felony",
    "possession of stolen property": "felony",
    "perjury": "felony",
    "obstruction of justice": "felony",
    "official misconduct": "felony",
    "immigration": "felony",
    "destruction of property": "felony",
    "solicitation": "felony",
    "attempt, nonviolent": "felony",
    # Lesser / misdemeanour / regulatory.
    "sex offender registration": "lesser",
    "other nonviolent misdemeanor": "lesser",
    "other violent misdemeanor": "lesser",
    "traffic offense": "lesser",
    "threats": "lesser",
    "stalking": "lesser",
    "failure to pay child support": "lesser",
    "menacing": "lesser",
    "filing a false report": "lesser",
    "harassment": "lesser",
}

# Longest keys first so a specific offense wins over a substring (e.g. "sexual
# assault" before "assault"). Sub/super offenses here share a tier, so this only
# ever sharpens the match, never changes the grade.
_TIER_KEYS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), tier)
    for term, tier in sorted(_OFFENSE_TIER.items(), key=lambda kv: -len(kv[0]))
)


def seriousness_tier(offense: str) -> str | None:
    """Return the seriousness tier key for an offense text, or ``None``.

    The offense is matched case-insensitively on whole-word keys, longest first,
    so both an exact NRE value ("Murder") and a free-text variant ("first-degree
    murder") grade to the same tier. An unknown or blank offense returns
    ``None`` — no grade rather than a guessed one (§3.2).
    """
    text = offense or ""
    for pattern, tier in _TIER_KEYS:
        if pattern.search(text):
            return tier
    return None


def seriousness_descriptor(offense: str) -> dict[str, str]:
    """Return the case-seriousness descriptor for an offense, or ``{}``.

    The descriptor is a pair of labelled facts — ``case_seriousness`` (the tier)
    and ``seriousness_basis`` (why) — that a caller merges into a flag's
    per-element ``descriptors``. It is never summed with anything (§3.1).
    """
    tier = seriousness_tier(offense)
    if tier is None:
        return {}
    return {
        "case_seriousness": _TIER_LABEL[tier],
        "seriousness_basis": SERIOUSNESS_MEANING[tier],
    }
