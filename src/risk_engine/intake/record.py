"""Structured intake record — a populated instance of the common schema.

An ``IntakeRecord`` holds the values extracted from one applicant's
questionnaire. Per README v2 Section 5 (the OCR + Structuring layer produces a
"confidence score per field") and Section 6.3, every field tracks OCR and
extraction confidence *separately* and keeps the verbatim source passage so a
human can verify it. Nothing here scores or ranks the case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import (
    COMMON_INTAKE_SCHEMA,
    IntakeCategory,
    field_by_key,
    near_universal_fields,
)


@dataclass
class IntakeField:
    """One extracted value, with separate OCR and extraction confidence."""

    key: str
    value: str
    ocr_confidence: float | None = None  # None = field was already digital
    extraction_confidence: float = 0.0
    source_passage: str = ""


@dataclass
class IntakeRecord:
    """A structured intake for one applicant.

    ``fields`` maps a schema key (see ``schema.COMMON_INTAKE_SCHEMA``) to the
    extracted ``IntakeField``. ``unmapped`` keeps questionnaire content the
    structuring layer could not confidently place, so nothing is silently lost.
    """

    applicant_ref: str = ""  # opaque local handle, not a score or judgment
    chapter: str = "PA"  # which chapter's form this came in on
    fields: dict[str, IntakeField] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)

    def set(
        self,
        key: str,
        value: str,
        *,
        ocr_confidence: float | None = None,
        extraction_confidence: float = 0.0,
        source_passage: str = "",
    ) -> IntakeField:
        """Record a value for a known schema key (validates the key exists)."""
        field_by_key(key)  # raises KeyError if not part of the common schema
        item = IntakeField(
            key=key,
            value=value,
            ocr_confidence=ocr_confidence,
            extraction_confidence=extraction_confidence,
            source_passage=source_passage,
        )
        self.fields[key] = item
        return item

    def get(self, key: str) -> IntakeField | None:
        return self.fields.get(key)

    def by_category(self, category: IntakeCategory) -> list[IntakeField]:
        """Populated fields in a category, in catalog order."""
        order = [f.key for f in COMMON_INTAKE_SCHEMA if f.category is category]
        return [self.fields[k] for k in order if k in self.fields]

    def missing_near_universal(self) -> list[str]:
        """Near-universal schema keys not yet populated.

        Surfaces gaps for follow-up. This is a completeness aid, never a signal
        about the merits of the case.
        """
        return [f.key for f in near_universal_fields() if f.key not in self.fields]
