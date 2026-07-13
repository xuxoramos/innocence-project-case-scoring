"""Case-record circumstance flagging step (keyword-seeded).

Flags the element categories that are **directly observable in the case record**
and need no external verification source (README v2 Section 5.2): informant
circumstance, witness/identification circumstance, evidence-preservation status,
and official-misconduct circumstances (prosecutor / judicial / police / expert)
described in the record itself. Discredited forensic methods are handled by
their own step, and the named-official registry step separately corroborates
misconduct against formal disciplinary records; the misconduct lexemes here only
flag conduct the case record itself describes, so they carry no
``verification_source``.

Each flag keeps OCR and extraction confidence separate and attaches the verbatim
*sentence* the hit came from (Section 6.3). Terms below the confidence floor are
recorded as features but suppressed as flags — a missed flag is more recoverable
than a misleading one. Cross-racial identification is emitted as a separate
witness/ID flag with an ``INFERRED`` basis and an inference note (Section 6.4).
Extraction is keyword-seeded for the POC; a learned extractor can replace the
lexicon without changing the interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import settings
from ..lexicons import load_rules
from ..models import Case, Flag, FlagBasis, FlagCategory
from .base import ProcessingStep, sentence_around


@dataclass(frozen=True)
class _Lexeme:
    """A group of synonymous terms that map to one category/basis."""

    label: str  # unique key for the features dict
    category: FlagCategory
    basis: FlagBasis
    terms: tuple[tuple[str, float], ...]  # (term, extraction_confidence)
    inference_note: str | None = None


#: Parsed ``lexicons/rules.json`` — the editable source of the lexemes and the
#: misconduct-type map below (spec v3 §10, item 2). Edit the JSON, not this module.
_RULES = load_rules()


def _lexeme_from_json(entry: dict) -> _Lexeme:
    """Build a :class:`_Lexeme` from one ``rules.json`` lexeme entry."""
    return _Lexeme(
        label=entry["label"],
        category=FlagCategory(entry["category"]),
        basis=FlagBasis(entry["basis"]),
        terms=tuple((term, conf) for term, conf in entry["terms"]),
        inference_note=entry.get("inference_note"),
    )


# Phrasing covers the paraphrases appellate opinions actually use, not just lay
# terms, to lift recall. Cross-racial ID is its own lexeme (inferred basis).
_LEXICON: tuple[_Lexeme, ...] = tuple(_lexeme_from_json(e) for e in _RULES["lexemes"])


# Pre-compile a word-boundary matcher per term so a term does not fire inside a
# longer token (e.g. "single witness" must be a whole phrase).
_COMPILED: tuple[tuple[_Lexeme, tuple[tuple[re.Pattern[str], float, str], ...]], ...] = tuple(
    (
        lex,
        tuple(
            (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), conf, term)
            for term, conf in lex.terms
        ),
    )
    for lex in _LEXICON
)


# Misconduct *type* + *gravity* descriptor per lexeme term (spec v3 §3.4, point 4
# / Appendix B), built from ``lexicons/rules.json`` ``misconduct_types``. Types
# are the NRE "Government Misconduct and Convicting the Innocent" (2020)
# categories; gravity reflects that fabrication and Brady concealment rank graver
# than improper argument (§5.2). Only terms that map to a specific type carry a
# descriptor — generic terms ("prosecutorial misconduct", "police misconduct")
# and judicial-conduct terms are left undescribed rather than forced into a type.
# These stay attached to the one element and are never summed (README v2 §3.1).
_MISCONDUCT_TYPE: dict[str, tuple[str, str]] = {
    term: (type_label, gravity)
    for term, (type_label, gravity) in _RULES["misconduct_types"].items()
}


class TabularStep(ProcessingStep):
    name = "tabular"

    def applies_to(self, case: Case) -> bool:
        return any(d.normalized_text for d in case.documents)

    def run(self, case: Case) -> Case:
        text = " ".join(d.normalized_text or "" for d in case.documents)
        for lex, patterns in _COMPILED:
            best: tuple[float, re.Match[str], str] | None = None
            for pattern, conf, term in patterns:
                match = pattern.search(text)
                if match is None:
                    continue
                if best is None or conf > best[0]:
                    best = (conf, match, term)
            # Suppress weak / crime-type-only hits below the floor (README 6.3).
            if best is None or best[0] < settings.confidence_floor:
                case.features[lex.label] = 0
                continue
            conf, match, term = best
            case.features[lex.label] = 1
            descriptors: dict[str, str] = {}
            type_info = _MISCONDUCT_TYPE.get(term)
            if type_info is not None:
                descriptors["misconduct_type"] = type_info[0]
                descriptors["type_gravity"] = type_info[1]
            case.flags.append(
                Flag(
                    category=lex.category,
                    basis=lex.basis,
                    extraction_confidence=conf,
                    source_passage=sentence_around(text, match.start(), match.end()),
                    inference_note=lex.inference_note,
                    descriptors=descriptors,
                )
            )
        case.has_tabular = True
        return case
