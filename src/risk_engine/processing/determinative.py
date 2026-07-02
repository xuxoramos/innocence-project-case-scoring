"""Outcome-determinative record-language step (spec v3 §3.4).

Attaches a *record-language signal* descriptor to an element flag when the case
record's own words single out that element's evidence as the only, principal, or
case-deciding proof — e.g. "the only evidence was the eyewitness identification"
or "the conviction rested entirely on the informant's testimony".

This is a **quoted signal, never an inference of pivotality** (README v2 §3.2).
A descriptor attaches only when a determinative *frame* ("only", "sole",
"rested on", "hinged on", "key witness", "linchpin", ...) co-occurs *in the same
sentence* with an *element noun* that names the flag's own element (eyewitness
identification -> witness/ID circumstance; informant / accomplice testimony ->
informant circumstance). Two further safeguards keep it honest:

* **Element-matched, gated by an existing flag.** The signal is only ever added
  to a flag the engine already produced for that same element category, so a
  stray frame+noun co-occurrence with no underlying flag adds nothing.
* **Verbatim, never asserted.** The whole sentence is stored so a reviewer reads
  the court's actual language; the engine never claims the element *was*
  dispositive, only that the record's wording singles it out. No co-occurrence
  -> no descriptor (an unknown is left blank, never guessed).

Scope is deliberately limited to the two single-element circumstance categories
(eyewitness identification and informant / accomplice testimony) where every
flag concerns the same element, so an element-matched signal cannot be
misattributed to a different sub-element. The descriptor hangs off the one
element and is never summed into a case-level number (§3.1).
"""

from __future__ import annotations

import re

from ..models import Case, FlagCategory
from .base import ProcessingStep, sentence_around

#: Determinative *frames*: wording that marks a present evidence element as
#: singular or case-deciding. Absence phrasings ("no forensic evidence") are
#: excluded on purpose — they describe what the record *lacks*, not the weight
#: of a present element, and pairing them with an element noun would invert the
#: meaning (README v2 §6.3 negation guard).
_FRAME = re.compile(
    r"\b("
    r"only|sole|lone|single"
    r"|uncorroborated"
    r"|rested (?:entirely |largely |primarily |solely )?(?:up)?on"
    r"|hinged (?:entirely |largely |primarily )?(?:up)?on"
    r"|turned (?:entirely |largely |primarily )?(?:up)?on"
    r"|based (?:solely|entirely|primarily|largely) (?:up)?on"
    r"|key (?:witness|evidence)"
    r"|principal (?:evidence|witness)"
    r"|primary evidence"
    r"|chief (?:evidence|witness)"
    r"|critical (?:evidence|witness|testimony)"
    r"|crux"
    r"|linchpin"
    r"|cornerstone"
    r"|central to the (?:state'?s |prosecution'?s |government'?s )?case"
    r"|but for"
    r")\b",
    re.IGNORECASE,
)

#: Element nouns per flag category. Each pattern names the element concretely
#: enough that a frame in the same sentence is a genuine determinative signal
#: about *that* element, not incidental legal boilerplate.
_ELEMENTS: dict[FlagCategory, re.Pattern[str]] = {
    FlagCategory.WITNESS_ID_CIRCUMSTANCE: re.compile(
        r"\b("
        r"eye[- ]?witness(?:es)?"
        r"|eyewitness (?:identification|testimony)"
        r"|identification of (?:the )?"
        r"(?:defendant|accused|perpetrator|suspect|assailant|robber|shooter|attacker)"
        r"|identification testimony"
        r"|victim'?s identification"
        r"|(?:photo(?:graphic)?|lineup|show[- ]?up) identification"
        r")\b",
        re.IGNORECASE,
    ),
    FlagCategory.INFORMANT_CIRCUMSTANCE: re.compile(
        r"\b("
        r"informant'?s?"
        r"|jailhouse informant"
        r"|accomplices?"
        r"|accomplice testimony"
        r"|co[- ]?defendant'?s?"
        r"|cooperating witness(?:es)?"
        r"|cooperator"
        r"|snitch"
        r")\b",
        re.IGNORECASE,
    ),
}

#: Honest wording for the attached descriptor: it points the reviewer at the
#: quoted passage and stops short of asserting the element was dispositive.
_SIGNAL_BASIS = (
    "the record's own wording singles out this evidence element as the only, "
    "principal, or case-deciding proof; read the quoted passage to judge its "
    "weight (README v2 §3.2)"
)


class DeterminativeStep(ProcessingStep):
    """Attach a verbatim outcome-determinative record signal to element flags."""

    name = "determinative"

    def applies_to(self, case: Case) -> bool:
        return bool(case.flags) and any(d.normalized_text for d in case.documents)

    def run(self, case: Case) -> Case:
        text = " ".join(d.normalized_text or "" for d in case.documents)
        if not text:
            return case
        # First determinative sentence per element category (only categories we
        # already hold a flag for are worth scanning).
        wanted = {flag.category for flag in case.flags} & set(_ELEMENTS)
        if not wanted:
            return case
        signals: dict[FlagCategory, str] = {}
        for match in _FRAME.finditer(text):
            sentence = sentence_around(text, match.start(), match.end())
            for category in wanted:
                if category in signals:
                    continue
                if _ELEMENTS[category].search(sentence):
                    signals[category] = " ".join(sentence.split())
            if len(signals) == len(wanted):
                break
        if not signals:
            return case
        for flag in case.flags:
            sentence = signals.get(flag.category)
            if sentence and "record_signal" not in flag.descriptors:
                flag.descriptors = {
                    **flag.descriptors,
                    "record_signal": sentence,
                    "signal_basis": _SIGNAL_BASIS,
                }
        return case
