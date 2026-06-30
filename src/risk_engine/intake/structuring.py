"""Structuring layer: raw questionnaire content -> structured IntakeRecord.

README v2 Section 5: the OCR + Structuring layer turns an applicant's intake
questionnaire into the common schema, with a confidence score per field. Real
handwriting OCR is out of scope for this milestone; this layer takes already-
extracted ``{label_or_key: value}`` content (e.g. from a fillable PDF, a typed
form, or a downstream OCR pass) and maps it onto ``COMMON_INTAKE_SCHEMA``.

Field labels vary by chapter ("Inmate number", "TDCJ number", "Identification
No." all mean the same thing), so a small alias table normalizes the common
variants. Anything it cannot confidently place is kept in ``unmapped`` rather
than dropped — nothing is silently lost, and nothing here scores the case.
"""

from __future__ import annotations

from collections.abc import Mapping

from .record import IntakeRecord
from .schema import field_by_key

# Confidence assigned when a value maps to a schema key directly vs. via an
# alias. These are structuring confidences, separate from OCR confidence.
_EXACT_KEY_CONFIDENCE = 0.95
_ALIAS_CONFIDENCE = 0.8

# Lower-cased chapter field labels -> common schema key. Built from the real
# forms surveyed in schema.CHAPTER_SOURCES.
_LABEL_ALIASES: dict[str, str] = {
    # personal / background
    "full name": "applicant_full_name",
    "name of applicant": "applicant_full_name",
    "applicant name": "applicant_full_name",
    "inmate number": "inmate_doc_id",
    "inmate no": "inmate_doc_id",
    "identification no": "inmate_doc_id",
    "identification number": "inmate_doc_id",
    "doc number": "inmate_doc_id",
    "tdcj number": "inmate_doc_id",
    "tdcj": "inmate_doc_id",
    "current facility": "current_facility",
    "facility": "current_facility",
    "current address": "current_address",
    "address": "current_address",
    "date of birth": "date_of_birth",
    "dob": "date_of_birth",
    "preferred language": "preferred_language",
    "race": "race_ethnicity",
    "ethnicity": "race_ethnicity",
    "race/ethnicity": "race_ethnicity",
    "highest grade completed": "highest_grade_completed",
    # conviction
    "crime convicted of": "offense_convicted_of",
    "crimes convicted of": "offense_convicted_of",
    "offense": "offense_convicted_of",
    "conviction": "offense_convicted_of",
    "where conviction occurred": "conviction_jurisdiction",
    "county of conviction": "conviction_jurisdiction",
    "city county and state of conviction": "conviction_jurisdiction",
    "court type": "court_type",
    "date of conviction": "date_of_conviction",
    "sentence": "sentence_received",
    "sentence received": "sentence_received",
    "case number": "case_number",
    "co-defendants": "co_defendants",
    "codefendants": "co_defendants",
    # claim of innocence
    "claims actual innocence": "claims_actual_innocence",
    "are you claiming innocence": "claims_actual_innocence",
    "basis for innocence": "innocence_rationale",
    "why you are innocent": "innocence_rationale",
    "where were you at the time of the crime": "applicant_whereabouts_activity",
    "alibi": "applicant_whereabouts_activity",
    "what police say happened": "prosecution_narrative",
    "what witnesses say happened": "prosecution_narrative",
    "victim": "victim_names",
    "victim names": "victim_names",
    # investigation
    "date of crime": "crime_date_time",
    "date of the crime": "crime_date_time",
    "investigating agency": "investigating_agency",
    "how you became a suspect": "how_became_suspect",
    "date of arrest": "date_of_arrest",
    "date crime was reported": "date_crime_reported",
    "where crime occurred": "crime_location",
    # trial
    "trial or plea": "disposition_type",
    "disposition": "disposition_type",
    "defense counsel": "defense_counsel",
    # post-conviction
    "appeals status": "appeals_status",
    "where you are in your appeals process": "appeals_status",
    "currently represented": "currently_represented",
    "do you have an attorney": "currently_represented",
    # evidence
    "dna evidence": "biological_dna_evidence_exists",
    "biological evidence": "biological_dna_evidence_exists",
    # materials
    "records you have": "records_on_hand",
    "materials on hand": "records_on_hand",
}


def _resolve_key(label_or_key: str) -> tuple[str | None, float]:
    """Return (schema_key, structuring_confidence) for an incoming label."""
    candidate = label_or_key.strip()
    try:
        field_by_key(candidate)
        return candidate, _EXACT_KEY_CONFIDENCE
    except KeyError:
        pass
    normalized = candidate.lower().rstrip(":.?").strip()
    key = _LABEL_ALIASES.get(normalized)
    if key is not None:
        return key, _ALIAS_CONFIDENCE
    return None, 0.0


def structure_intake(
    raw_fields: Mapping[str, str],
    *,
    chapter: str = "PA",
    applicant_ref: str = "",
    ocr_confidences: Mapping[str, float] | None = None,
) -> IntakeRecord:
    """Map raw ``{label_or_key: value}`` content onto the common schema.

    Values whose label cannot be placed are appended to ``record.unmapped`` as
    ``"label: value"`` so they remain visible for manual review.
    """
    record = IntakeRecord(applicant_ref=applicant_ref, chapter=chapter)
    ocr_confidences = ocr_confidences or {}
    for label, value in raw_fields.items():
        if value is None or str(value).strip() == "":
            continue
        key, confidence = _resolve_key(label)
        if key is None:
            record.unmapped.append(f"{label}: {value}")
            continue
        record.set(
            key,
            str(value).strip(),
            ocr_confidence=ocr_confidences.get(label),
            extraction_confidence=confidence,
            source_passage=str(value).strip(),
        )
    return record
