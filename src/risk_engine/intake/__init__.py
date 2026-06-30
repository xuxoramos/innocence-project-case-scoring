"""Intake processing: the common schema and structured intake records.

This is the new front of the pipeline under README v2 — structuring an
applicant's intake questionnaire into a common, cross-chapter schema. It does
not score, rank, or judge a case.
"""

from __future__ import annotations

from .record import IntakeField, IntakeRecord
from .schema import (
    CHAPTER_SOURCES,
    COMMON_INTAKE_SCHEMA,
    ELIGIBILITY_GATES,
    EligibilityGate,
    FieldSpec,
    IntakeCategory,
    Universality,
    field_by_key,
    fields_for,
    near_universal_fields,
)
from .structuring import structure_intake

__all__ = [
    "CHAPTER_SOURCES",
    "COMMON_INTAKE_SCHEMA",
    "ELIGIBILITY_GATES",
    "EligibilityGate",
    "FieldSpec",
    "IntakeCategory",
    "IntakeField",
    "IntakeRecord",
    "Universality",
    "field_by_key",
    "fields_for",
    "near_universal_fields",
    "structure_intake",
]
