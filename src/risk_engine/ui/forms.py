"""Pure view helpers for the web UI (no framework imports, so they unit-test).

The FastAPI app stays a thin shell: these functions turn the intake schema into
form sections and turn an assembled :class:`~risk_engine.packet.CasePacket` into
a plain dict the Jinja template renders. Keeping the logic here (not in the
routes or the templates) means the rendering can be tested without spinning up a
server, and the template has no business logic in it.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..intake.schema import IntakeCategory, field_by_key, near_universal_fields
from ..packet import CasePacket, RecordSearchStatus
from ..models import FlagBasis

#: Schema keys rendered as multi-line text areas rather than single-line inputs.
_MULTILINE_KEYS = frozenset(
    {
        "innocence_rationale",
        "applicant_whereabouts_activity",
        "prosecution_narrative",
        "applicant_theory",
        "key_prosecution_evidence",
        "records_on_hand",
    }
)

#: Human label + CSS state class per record-search status (Section 6.6 colours).
_STATUS_DISPLAY: dict[RecordSearchStatus, tuple[str, str]] = {
    RecordSearchStatus.FOUND_WITH_FLAGS: ("Found — has flags", "found-flags"),
    RecordSearchStatus.FOUND_NO_FLAGS: ("Found — no flags", "found-clean"),
    RecordSearchStatus.NOT_FOUND: ("Not found (gap)", "not-found"),
}

#: Meta form fields are prefixed so they never collide with schema keys.
SOURCE_FIELD = "_source"
APPLICANT_REF_FIELD = "_applicant_ref"
CHAPTER_FIELD = "_chapter"


def _pretty(value: str) -> str:
    return value.replace("_", " ").capitalize()


def form_field_groups() -> list[dict]:
    """Near-universal intake fields grouped by category, for the form template."""
    groups: list[dict] = []
    for category in IntakeCategory:
        fields = [f for f in near_universal_fields() if f.category is category]
        if not fields:
            continue
        groups.append(
            {
                "category": category.value,
                "label": _pretty(category.value),
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "multiline": f.key in _MULTILINE_KEYS,
                    }
                    for f in fields
                ],
            }
        )
    return groups


def parse_intake_form(form: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split a submitted form into (schema raw_fields, meta).

    Meta keys (source, applicant ref, chapter) are prefixed with ``_``. Blank
    values are dropped so nothing is recorded as an empty extraction.
    """
    raw_fields: dict[str, str] = {}
    meta: dict[str, str] = {}
    for key, value in form.items():
        value = (value or "").strip()
        if not value:
            continue
        if key.startswith("_"):
            meta[key] = value
        else:
            raw_fields[key] = value
    return raw_fields, meta


def _flag_view(flag) -> dict:
    return {
        "basis": flag.basis.value,
        "inferred": flag.basis is FlagBasis.INFERRED,
        "extraction_confidence": f"{flag.extraction_confidence:.2f}",
        "ocr_confidence": ("n/a" if flag.ocr_confidence is None else f"{flag.ocr_confidence:.2f}"),
        "source_passage": " ".join(flag.source_passage.split()),
        "inference_note": flag.inference_note,
        "verification_source": flag.verification_source,
    }


def packet_view(packet: CasePacket) -> dict:
    """Turn an assembled packet into a plain dict for the Jinja template."""
    intake_groups: list[dict] = []
    missing: list[str] = []
    if packet.intake is not None:
        for category in IntakeCategory:
            fields = packet.intake.by_category(category)
            if not fields:
                continue
            intake_groups.append(
                {
                    "label": _pretty(category.value),
                    "fields": [
                        {"label": field_by_key(f.key).label, "value": f.value} for f in fields
                    ],
                }
            )
        missing = packet.intake.missing_near_universal()

    records = []
    for r in packet.records:
        label, state = _STATUS_DISPLAY[r.status]
        records.append(
            {
                "record_type": r.record_type,
                "status_label": label,
                "status_class": state,
                "detail": r.detail,
            }
        )

    flag_groups = [
        {
            "label": _pretty(group.category.value),
            "flags": [_flag_view(f) for f in group.flags],
        }
        for group in packet.flag_groups
    ]

    return {
        "case_id": packet.case_id,
        "scope_statement": packet.scope_statement,
        "intake_groups": intake_groups,
        "missing_near_universal": missing,
        "records": records,
        "flag_groups": flag_groups,
        "total_flags": packet.total_flags,
        "has_flags": packet.has_flags,
    }
