"""Forensic-method flagging step.

Scans normalized case text for discredited or scientifically-limited forensic
methods (see :mod:`risk_engine.forensic`) and emits a
``DISCREDITED_FORENSIC_METHOD`` flag for each, with the independent scientific
citation attached as the flag's ``verification_source`` (README v2 Section 5.2).
The method name itself is directly stated in the record; the *discrediting* is
verified against the case-independent literature, never against case outcomes.
"""

from __future__ import annotations

from ..config import settings
from ..forensic import TIER_MEANING, find_forensic_methods
from ..models import Case, Flag, FlagBasis, FlagCategory
from .base import ProcessingStep, sentence_around


class ForensicMethodStep(ProcessingStep):
    name = "forensic"

    def applies_to(self, case: Case) -> bool:
        return any(d.normalized_text for d in case.documents)

    def run(self, case: Case) -> Case:
        text = " ".join(d.normalized_text or "" for d in case.documents)
        for hit in find_forensic_methods(text):
            if hit.ref.confidence < settings.confidence_floor:
                continue
            descriptors: dict[str, str] = {}
            if hit.ref.tier:
                descriptors["discreditation_tier"] = hit.ref.tier
                descriptors["tier_meaning"] = TIER_MEANING.get(hit.ref.tier, "")
                descriptors["citing_authority"] = hit.ref.authority
            case.flags.append(
                Flag(
                    category=FlagCategory.DISCREDITED_FORENSIC_METHOD,
                    basis=FlagBasis.DIRECTLY_STATED,
                    extraction_confidence=hit.ref.confidence,
                    source_passage=sentence_around(text, hit.start, hit.end),
                    verification_source=f"{hit.ref.method} ({hit.ref.status}): {hit.ref.source}",
                    descriptors=descriptors,
                )
            )
        return case
