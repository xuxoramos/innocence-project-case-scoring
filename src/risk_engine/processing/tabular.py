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


# Phrasing covers the paraphrases appellate opinions actually use, not just lay
# terms, to lift recall. Cross-racial ID is its own lexeme (inferred basis).
_LEXICON: tuple[_Lexeme, ...] = (
    _Lexeme(
        "informant",
        FlagCategory.INFORMANT_CIRCUMSTANCE,
        FlagBasis.DIRECTLY_STATED,
        (
            ("jailhouse informant", 0.85),
            ("jail-house informant", 0.85),
            ("cooperation agreement", 0.75),
            ("cooperating witness", 0.7),
            ("confidential informant", 0.7),
            ("sentence reduction", 0.7),
            ("accomplice testimony", 0.65),
            # Perjury / false-accusation phrasings (NRE maps these to the informant
            # column). Corpus-grounded; the bare token "perjur" is boilerplate
            # ("under penalty of perjury") so only these specific phrases fire.
            ("suborned perjury", 0.8),
            ("suborn perjury", 0.8),
            ("perjured testimony", 0.75),
            ("false testimony", 0.65),
            ("in exchange for", 0.6),
            ("plea deal", 0.5),  # ubiquitous, not per se informant risk -> suppressed
        ),
    ),
    _Lexeme(
        "witness_id",
        FlagCategory.WITNESS_ID_CIRCUMSTANCE,
        FlagBasis.DIRECTLY_STATED,
        (
            ("recanted", 0.85),
            ("recantation", 0.85),
            ("sole eyewitness", 0.8),
            ("lone eyewitness", 0.8),
            ("suggestive lineup", 0.8),
            ("suggestive identification", 0.8),
            ("only eyewitness", 0.75),
            ("single witness", 0.7),
            ("uncorroborated", 0.7),
            ("no corroborating", 0.7),
            ("show-up identification", 0.7),
            ("low light", 0.6),
        ),
    ),
    _Lexeme(
        "cross_racial",
        FlagCategory.WITNESS_ID_CIRCUMSTANCE,
        FlagBasis.INFERRED,
        (
            ("cross-racial", 0.7),
            ("cross racial", 0.7),
            ("other-race", 0.65),
            ("different race", 0.65),
        ),
        inference_note=(
            "cross-racial identification inferred from the record; verify against "
            "the stated races of witness and defendant (README v2 Section 6.4)"
        ),
    ),
    _Lexeme(
        "evidence_preservation",
        FlagCategory.EVIDENCE_PRESERVATION,
        FlagBasis.DIRECTLY_STATED,
        (
            ("destroyed evidence", 0.8),
            ("lost evidence", 0.8),
            ("untested rape kit", 0.85),
            ("chain of custody", 0.7),
            ("evidence locker", 0.7),
            ("not tested", 0.7),
            ("biological evidence", 0.65),
            ("rape kit", 0.5),  # present in most sexual-assault cases -> suppressed
        ),
    ),
    # Official-misconduct circumstances described *in the record*. Confidences are
    # seeds; calibration against the NRE per-role columns adjusts them. No
    # verification_source — corroborating the named actor is the registry's job.
    _Lexeme(
        "prosecutor_misconduct",
        FlagCategory.PROSECUTOR_MISCONDUCT,
        FlagBasis.DIRECTLY_STATED,
        (
            ("brady violation", 0.85),
            ("withheld exculpatory", 0.85),
            ("suppressed exculpatory", 0.85),
            ("brady material", 0.8),
            ("failed to disclose exculpatory", 0.8),
            ("prosecutorial misconduct", 0.8),
            ("knowingly presented false", 0.8),
            ("knowingly used false", 0.8),
            ("knowingly elicited false", 0.8),
            ("failed to correct false testimony", 0.8),
            ("giglio", 0.75),
            ("improper closing argument", 0.65),
            ("improper argument", 0.6),
        ),
    ),
    _Lexeme(
        "judicial_misconduct",
        FlagCategory.JUDICIAL_MISCONDUCT,
        FlagBasis.DIRECTLY_STATED,
        (
            ("judicial misconduct", 0.85),
            ("judge was removed", 0.8),
            ("removed from the bench", 0.8),
            ("recused for bias", 0.75),
            ("ex parte communication", 0.65),
        ),
    ),
    _Lexeme(
        "police_misconduct",
        FlagCategory.POLICE_MISCONDUCT,
        FlagBasis.DIRECTLY_STATED,
        (
            ("fabricated evidence", 0.85),
            ("planted evidence", 0.85),
            ("coerced confession", 0.85),
            ("falsified police report", 0.8),
            ("fabrication of evidence", 0.8),
            ("manufactured evidence", 0.8),
            ("falsifying evidence", 0.8),
            ("police misconduct", 0.8),
            ("coerced statement", 0.75),
            ("coercive interrogation", 0.65),
        ),
    ),
    _Lexeme(
        "expert_witness_misconduct",
        FlagCategory.EXPERT_WITNESS_MISCONDUCT,
        FlagBasis.DIRECTLY_STATED,
        (
            ("fabricated test results", 0.85),
            ("falsified the analysis", 0.85),
            ("fraudulent analysis", 0.85),
            ("overstated the certainty", 0.8),
            ("exaggerated the certainty", 0.8),
            ("misrepresented the results", 0.75),
        ),
    ),
)

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
# / Appendix B). Types are the NRE "Government Misconduct and Convicting the
# Innocent" (2020) categories; gravity reflects that fabrication and Brady
# concealment rank graver than improper argument (§5.2). Only terms that map to
# a specific type carry a descriptor — generic terms ("prosecutorial
# misconduct", "police misconduct") and judicial-conduct terms are left
# undescribed rather than forced into a type. These stay attached to the one
# element and are never summed into a case-level number (README v2 §3.1).
_FABRICATION = ("fabricating evidence", "aggravating (fabrication)")
_BRADY = ("concealing exculpatory evidence (Brady)", "aggravating (Brady concealment)")
_INTERROGATION = ("misconduct in interrogations", "serious")
_PERJURY = ("perjury / false accusation", "serious")
_FALSE_TESTIMONY = ("false or misleading testimony", "serious")
_IMPROPER_ARGUMENT = ("improper argument at trial", "lesser (not fabrication or Brady)")

_MISCONDUCT_TYPE: dict[str, tuple[str, str]] = {
    "brady violation": _BRADY,
    "withheld exculpatory": _BRADY,
    "suppressed exculpatory": _BRADY,
    "brady material": _BRADY,
    "failed to disclose exculpatory": _BRADY,
    "giglio": _BRADY,
    "knowingly presented false": _PERJURY,
    "knowingly used false": _PERJURY,
    "knowingly elicited false": _PERJURY,
    "failed to correct false testimony": _PERJURY,
    "improper closing argument": _IMPROPER_ARGUMENT,
    "improper argument": _IMPROPER_ARGUMENT,
    "fabricated evidence": _FABRICATION,
    "planted evidence": _FABRICATION,
    "falsified police report": _FABRICATION,
    "fabrication of evidence": _FABRICATION,
    "manufactured evidence": _FABRICATION,
    "falsifying evidence": _FABRICATION,
    "coerced confession": _INTERROGATION,
    "coerced statement": _INTERROGATION,
    "coercive interrogation": _INTERROGATION,
    "fabricated test results": _FABRICATION,
    "falsified the analysis": _FABRICATION,
    "fraudulent analysis": _FABRICATION,
    "overstated the certainty": _FALSE_TESTIMONY,
    "exaggerated the certainty": _FALSE_TESTIMONY,
    "misrepresented the results": _FALSE_TESTIMONY,
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
