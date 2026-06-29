"""Optional tabular feature-extraction step.

Turns normalized text into a tabular feature matrix (README 5). Produces a
``Flag`` per detected NRE failure category, keeping OCR and extraction
confidence separate and attaching the verbatim source passage. Flags below the
confidence floor are suppressed entirely (README 6.3). Extraction is keyword-
seeded for the POC; a learned extractor can replace ``_CATEGORY_TERMS`` without
changing the interface.
"""

from __future__ import annotations

from ..config import settings
from ..models import Case, Flag, FlagBasis, FlagCategory
from .base import ProcessingStep

_CATEGORY_TERMS: dict[FlagCategory, tuple[str, ...]] = {
    FlagCategory.FORENSIC_SCIENCE_FLAWS: ("hair microscopy", "bite-mark", "arson"),
    FlagCategory.WITNESS_RELIABILITY: ("single witness", "no corroborating", "low light"),
    FlagCategory.CROSS_RACIAL_EYEWITNESS_ID: ("cross-racial", "different race"),
    FlagCategory.INFORMANT_RISK: ("jailhouse informant", "sentence reduction", "plea deal"),
    FlagCategory.EVIDENCE_PRESERVATION: ("evidence locker", "not tested", "rape kit"),
}


class TabularStep(ProcessingStep):
    name = "tabular"

    def applies_to(self, case: Case) -> bool:
        return any(d.normalized_text for d in case.documents)

    def run(self, case: Case) -> Case:
        text = " ".join(d.normalized_text or "" for d in case.documents).lower()
        for category, terms in _CATEGORY_TERMS.items():
            hit = next((t for t in terms if t in text), None)
            if not hit:
                case.features[category.value] = 0
                continue
            extraction_conf = 0.75
            if extraction_conf < settings.confidence_floor:
                continue
            basis = (
                FlagBasis.INFERRED
                if category is FlagCategory.CROSS_RACIAL_EYEWITNESS_ID
                else FlagBasis.DIRECTLY_STATED
            )
            case.features[category.value] = 1
            case.flags.append(
                Flag(
                    category=category,
                    basis=basis,
                    extraction_confidence=extraction_conf,
                    source_passage=hit,
                )
            )
        case.has_tabular = True
        return case
