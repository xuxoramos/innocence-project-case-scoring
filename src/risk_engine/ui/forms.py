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
from ..labels import NRE_FACTOR_COLUMNS
from ..packet import CasePacket, RecordSearchStatus
from ..models import FlagBasis, FlagCategory
from ..casefiles import DISPOSITION_DISPLAY, DISPOSITION_UNDECIDED

#: Plain-language rendering of a flag's basis (never the raw enum token). A flag
#: is either quoted from the record or inferred from what the record says.
BASIS_DISPLAY: dict[str, str] = {
    FlagBasis.DIRECTLY_STATED.value: "stated in the record",
    FlagBasis.INFERRED.value: "inferred from the record",
}

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
    RecordSearchStatus.FOUND_WITH_FLAGS: ("Record found \u2014 flagged", "found-flags"),
    RecordSearchStatus.FOUND_NO_FLAGS: ("Record found \u2014 none flagged", "found-clean"),
    RecordSearchStatus.NOT_FOUND: ("No court record found", "not-found"),
}

#: Meta form fields are prefixed so they never collide with schema keys.
SOURCE_FIELD = "_source"
APPLICANT_REF_FIELD = "_applicant_ref"
CHAPTER_FIELD = "_chapter"
#: Carries the upload token of a prefilled PDF from the compare view through save,
#: so the original PDF can be promoted into the case store (spec v3 point 1).
PDF_TOKEN_FIELD = "_pdf_token"
#: Carries the original uploaded filename alongside the token, for display only.
PDF_NAME_FIELD = "_pdf_name"


#: Human label + one-line description per schema-checkable FlagCategory. Keyed by
#: the enum *value* so it works on both the stored labels and predicted flags.
#: These describe what the category means; they never rank or weight it (§3.1).
FACTOR_DISPLAY: dict[str, tuple[str, str]] = {
    FlagCategory.DISCREDITED_FORENSIC_METHOD.value: (
        "Discredited forensic method",
        "A forensic technique relied on at trial that has since been scientifically "
        "discredited or shown to be unreliable.",
    ),
    FlagCategory.PROSECUTOR_MISCONDUCT.value: (
        "Prosecutor misconduct",
        "Misconduct by the prosecuting attorney, such as withholding exculpatory "
        "evidence or improper argument.",
    ),
    FlagCategory.JUDICIAL_MISCONDUCT.value: (
        "Judicial misconduct",
        "Misconduct by the trial judge affecting the fairness of the proceeding.",
    ),
    FlagCategory.POLICE_MISCONDUCT.value: (
        "Police misconduct",
        "Misconduct by law-enforcement officers during the investigation or arrest.",
    ),
    FlagCategory.EXPERT_WITNESS_MISCONDUCT.value: (
        "Forensic-analyst / expert misconduct",
        "Misconduct by a forensic analyst or expert witness, including misleading "
        "or fabricated testimony.",
    ),
    FlagCategory.OTHER_OFFICIAL_MISCONDUCT.value: (
        "Other official misconduct",
        "Misconduct by an official outside the prosecutor / judge / police / "
        "forensic-analyst roles (for example a child-welfare or corrections "
        "official), sourced from a formal public record.",
    ),
    FlagCategory.INFORMANT_CIRCUMSTANCE.value: (
        "Informant / false accusation",
        "A jailhouse or incentivized informant, or perjury / a knowingly false "
        "accusation against the defendant.",
    ),
    FlagCategory.WITNESS_ID_CIRCUMSTANCE.value: (
        "Eyewitness identification",
        "Mistaken eyewitness identification, including cross-racial identification.",
    ),
    FlagCategory.EVIDENCE_PRESERVATION.value: (
        "Evidence / DNA",
        "DNA or physical-evidence issues bearing on preservation, testing, or "
        "later exoneration.",
    ),
    FlagCategory.VULNERABLE_DEFENDANT_CIRCUMSTANCE.value: (
        "Vulnerable-defendant circumstance",
        "Record facts around the confession/interrogation (a minor or "
        "intellectually-disabled defendant, or a prolonged interrogation). Flags "
        "the circumstance only — never that a confession was false.",
    ),
}

#: Descriptions for the NRE factors the tool has no schema check for — the
#: known blind spots (§6.5). Keyed by the NRE factor-column name stored verbatim.
BLIND_SPOT_DISPLAY: dict[str, str] = {
    "False Confession": (
        "The defendant gave a confession later shown to be false. The tool has "
        "no way to check this from the intake record, so it is a known blind spot: "
        "a factor the tool can never flag on its own."
    ),
    "Official Misconduct": (
        "The NRE roll-up of official misconduct. The per-role columns (prosecutor, "
        "judge, police, forensic analyst) carry the detail, so this roll-up is left "
        "unchecked to avoid double-counting."
    ),
    "Inadequate Legal Defense": (
        "Ineffective assistance of defense counsel. The tool has no way to check "
        "this from the intake record, so it is a known blind spot: a factor the "
        "tool can never flag on its own."
    ),
}

#: The NRE factor-column(s) that back each schema-checkable category. This is the
#: concrete data behind a "checkable" tag: the Registry field the tool reads to
#: verify the factor. Inverted from ``labels.NRE_FACTOR_COLUMNS`` so the detail
#: view can show *why* a factor is checkable, not just that it is.
CATEGORY_TO_NRE_COLUMNS: dict[str, list[str]] = {}
for _col, _cat in NRE_FACTOR_COLUMNS.items():
    CATEGORY_TO_NRE_COLUMNS.setdefault(_cat.value, []).append(_col)
for _cat_value in CATEGORY_TO_NRE_COLUMNS:
    CATEGORY_TO_NRE_COLUMNS[_cat_value].sort()

#: Why each blind-spot factor cannot be checked — the concrete rationale behind a
#: "blind spot" tag, keyed by the NRE factor-column name stored verbatim.
BLIND_SPOT_REASON: dict[str, str] = {
    "False Confession": (
        "No intake-schema field records a confession, so the tool has no data to "
        "test this factor against."
    ),
    "Official Misconduct": (
        "This is the Registry's rolled-up misconduct total. The individual "
        "prosecutor, judge, police, and forensic-analyst factors carry the "
        "specifics and are checked on their own, so the rollup is left unchecked to "
        "avoid counting the same conduct twice."
    ),
    "Inadequate Legal Defense": (
        "No intake-schema field records the quality of defense counsel, so the "
        "tool has no data to test this factor against."
    ),
}


def factor_display(value: str) -> tuple[str, str]:
    """Human label + description for a FlagCategory value (falls back gracefully)."""
    return FACTOR_DISPLAY.get(value, (_pretty(value), ""))


def _checkable_rationale(value: str) -> str:
    """Plain-language reason a factor is tagged "checkable", naming the NRE field.

    The concrete data behind the tag: the Registry factor-column(s) the tool
    reads to verify this factor. Falls back to a generic sentence if the value
    is not one of the mapped categories.
    """
    cols = CATEGORY_TO_NRE_COLUMNS.get(value, [])
    if not cols:
        return "The tool has a check for this factor."
    quoted = " or ".join(f"\u201c{c}\u201d" for c in cols)
    field_word = "field" if len(cols) == 1 else "fields"
    return (
        f"Tagged checkable because the National Registry records it in its "
        f"{quoted} {field_word}, which the tool reads to verify the factor."
    )


def intake_form_view(intake) -> list[dict]:
    """Render an :class:`~risk_engine.intake.record.IntakeRecord` as form groups.

    Mirrors the live intake form: the near-universal §5.1 fields grouped by
    category, each shown with its value where the back-fill populated it and
    flagged ``provided=False`` (rendered as "not provided") where the NRE has no
    questionnaire prose to fill it. This lets the case-detail page present a
    stored exoneration exactly as an intake staffer would see the form.
    """
    groups: list[dict] = []
    for category in IntakeCategory:
        specs = [f for f in near_universal_fields() if f.category is category]
        if not specs:
            continue
        fields = []
        for spec in specs:
            item = intake.get(spec.key)
            fields.append(
                {
                    "label": spec.label,
                    "value": item.value if item else "",
                    "provided": item is not None,
                    "source": item.source_passage if item else "",
                }
            )
        groups.append(
            {
                "label": _pretty(category.value),
                "fields": fields,
                "provided_count": sum(1 for f in fields if f["provided"]),
            }
        )
    return groups



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


#: Intake schema key -> the :class:`~risk_engine.store.StoredCase` attribute whose
#: distinct registry values seed that field's autocomplete. Additive only: these
#: are HTML ``<datalist>`` suggestions, so the fields stay free text and the intake
#: schema is unchanged (spec v3, point 1). Consistent, canonical spellings here
#: improve the downstream name/jurisdiction record matching.
DATALIST_FIELDS: dict[str, str] = {
    "offense_convicted_of": "crime",
    "conviction_jurisdiction": "jurisdiction",
}


def intake_datalists(store) -> dict[str, list[str]]:
    """Distinct exoneration-registry values per autocomplete-eligible field.

    Returns ``{schema_key: sorted distinct values}`` for the fields in
    :data:`DATALIST_FIELDS`, drawn from the confirmed-exoneration store. Empty
    values are dropped. Suggestions only — never a constraint on what a reviewer
    may type.
    """
    out: dict[str, list[str]] = {}
    for key, attr in DATALIST_FIELDS.items():
        values = {getattr(case, attr, "") for case in store.cases}
        out[key] = sorted(v for v in values if v)
    return out


def prefilled_form_groups(intake) -> list[dict]:
    """Editable intake-form groups pre-populated from a parsed PDF (spec v3 point 1).

    Same shape as :func:`form_field_groups` (so the compare view renders identical
    inputs) but each field carries the ``value`` extracted from the uploaded PDF,
    ready for the reviewer to confirm or correct against the original shown beside
    it. Blank where nothing was extracted — never invented.
    """
    groups: list[dict] = []
    for category in IntakeCategory:
        specs = [f for f in near_universal_fields() if f.category is category]
        if not specs:
            continue
        fields = []
        for spec in specs:
            item = intake.get(spec.key)
            fields.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "multiline": spec.key in _MULTILINE_KEYS,
                    "value": item.value if item else "",
                }
            )
        groups.append(
            {
                "category": category.value,
                "label": _pretty(category.value),
                "fields": fields,
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


# Human labels for the per-element severity/frequency descriptors (spec v3 §3.4,
# point 4). Order here is the display order; unknown keys fall back to a
# prettified key so a new descriptor never breaks the view.
_DESCRIPTOR_LABELS: dict[str, str] = {
    "discreditation_tier": "discreditation tier",
    "tier_meaning": "tier meaning",
    "citing_authority": "citing authority",
    "misconduct_type": "misconduct type",
    "type_gravity": "type gravity",
    "repeat_findings": "formal findings on record",
    "frequency_note": "frequency",
    "record_signal": "outcome-determinative record signal",
    "signal_basis": "signal basis",
    "case_seriousness": "case seriousness",
    "seriousness_basis": "seriousness basis",
}


def _descriptor_view(descriptors: dict[str, str]) -> list[dict]:
    """Order and label per-element descriptors for the templates.

    Descriptors are labelled facts about the one element they hang off (a
    forensic tier, a misconduct type/gravity, a repeat-offender count). They are
    never combined into a case-level number (README v2 §3.1).
    """
    ordered = [k for k in _DESCRIPTOR_LABELS if k in descriptors]
    ordered += [k for k in descriptors if k not in _DESCRIPTOR_LABELS]
    return [
        {"label": _DESCRIPTOR_LABELS.get(k, _pretty(k)), "value": descriptors[k]}
        for k in ordered
    ]


def _reference_context(category: str, reference) -> dict | None:
    """Population frequency for a category, or ``None`` if not tracked/absent.

    ``reference`` is the map from :func:`risk_engine.reference.category_reference`.
    The result is a descriptive population fact (how many confirmed exonerations
    carried this NRE factor), never a prediction about the case at hand (§3.2).
    """
    if not reference:
        return None
    ctx = reference.get(category)
    if not ctx or ctx.get("count", 0) <= 0:
        return None
    return {"count": ctx["count"], "total": ctx["total"]}


def _flag_view(flag, reference=None) -> dict:
    return {
        "basis": flag.basis.value,
        "basis_label": BASIS_DISPLAY.get(flag.basis.value, flag.basis.value),
        "inferred": flag.basis is FlagBasis.INFERRED,
        "extraction_confidence": f"{flag.extraction_confidence:.2f}",
        "ocr_confidence": ("n/a" if flag.ocr_confidence is None else f"{flag.ocr_confidence:.2f}"),
        "source_passage": " ".join(flag.source_passage.split()),
        "inference_note": flag.inference_note,
        "verification_source": flag.verification_source,
        "descriptors": _descriptor_view(flag.descriptors),
        "reference": _reference_context(flag.category.value, reference),
    }


def packet_view(packet: CasePacket, reference=None) -> dict:
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
            "flags": [_flag_view(f, reference) for f in group.flags],
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
        "notes": list(packet.notes),
    }


def case_detail_view(case, ip_case=None) -> dict:
    """Enrich one :class:`~risk_engine.store.StoredCase` for the detail template.

    Turns the flat stored record into a display dict: the schema-checkable NRE
    factors and every engine flag get a human label and a plain-language
    description, the blind-spot factors get their §6.5 explanation, and an
    Innocence Project match (``ip_case``) contributes its case-page link and
    exoneration year. Nothing here scores or ranks — each factor and flag is
    described on its own (§3.1).
    """
    factors = [
        {
            "value": v,
            "label": factor_display(v)[0],
            "description": factor_display(v)[1],
            "sources": CATEGORY_TO_NRE_COLUMNS.get(v, []),
            "rationale": _checkable_rationale(v),
        }
        for v in case.labels
    ]
    blind_spots = [
        {
            "name": f,
            "description": BLIND_SPOT_DISPLAY.get(f, "NRE blind-spot factor the tool has no way to check."),
            "rationale": BLIND_SPOT_REASON.get(
                f, "No intake-schema field maps to this factor, so the tool has no data to check it."
            ),
        }
        for f in case.unmapped_factors
    ]
    predicted = [
        {"value": v, "label": factor_display(v)[0], "description": factor_display(v)[1]}
        for v in case.predicted
    ]
    flags = [
        {
            "element": factor_display(f.category)[0],
            "element_description": factor_display(f.category)[1],
            "basis": BASIS_DISPLAY.get(f.basis, _pretty(f.basis)),
            "extraction_confidence": f"{f.extraction_confidence:.2f}",
            "verification_source": f.verification_source,
            "source_passage": " ".join((f.source_passage or "").split()),
            "descriptors": _descriptor_view(f.descriptors),
        }
        for f in case.flags
    ]
    ip = None
    if ip_case is not None:
        ip = {
            "url": ip_case.url,
            "exoneration_year": ip_case.exoneration_year,
            "state": ip_case.state,
        }
    return {
        "name": case.name,
        "nre_id": case.nre_id,
        "provenance": case.provenance,
        "state": case.state,
        "county": case.county,
        "jurisdiction": case.jurisdiction,
        "crime": case.crime,
        "crime_year": case.crime_year,
        "conviction_year": case.conviction_year,
        "matched": case.matched,
        "innocence_project": case.innocence_project,
        "intake_form": intake_form_view(case.to_intake()),
        "factors": factors,
        "blind_spots": blind_spots,
        "predicted": predicted,
        "flags": flags,
        "factor_count": len(factors) + len(blind_spots),
        "flag_count": len(flags),
        "ip": ip,
    }


def case_file_view(case_file, reference=None) -> dict:
    """Enrich one submitted :class:`~risk_engine.casefiles.CaseFile` for display.

    Shows the saved intake as the same §5.1 form the reviewer filled in, plus the
    record-retrieval status (``NOT_STARTED`` in phase 1 — no court records pulled
    yet, an unstarted retrieval, never a clean result per §6.6) and any intake
    content the structuring layer could not place. Once records are linked the
    persisted per-element flags are shown, each with its reviewer disposition —
    still per-element and never combined into a case-level number (§3.1).
    """
    flag_groups = _stored_flag_groups(case_file.flags, reference)
    return {
        "case_id": case_file.case_id,
        "name": case_file.name,
        "provenance": case_file.provenance,
        "chapter": case_file.chapter,
        "applicant_ref": case_file.applicant_ref,
        "submitted_at": case_file.submitted_at,
        "jurisdiction": case_file.jurisdiction,
        "crime": case_file.crime,
        "conviction_year": case_file.conviction_year,
        "record_status": case_file.record_status,
        "record_status_label": case_file.record_status_label,
        "record_terminal": case_file.record_retrieval_terminal,
        "record_searches": case_file.record_search_views,
        "linked_record_count": case_file.linked_record_count,
        "retrieval_error": case_file.retrieval_error,
        "retrieved_at": case_file.retrieved_at,
        "has_pdf": case_file.has_pdf,
        "pdf_original_name": case_file.pdf_original_name,
        "intake_form": intake_form_view(case_file.to_intake()),
        "unmapped": list(case_file.unmapped),
        "flag_groups": flag_groups,
        "flag_count": sum(len(g["flags"]) for g in flag_groups),
        "has_flags": bool(flag_groups),
        "notes": list(case_file.notes),
    }


def stored_flag_view(flag: dict, reference=None) -> dict:
    """Enrich one persisted case-file flag dict for the template (with disposition)."""
    label, description = factor_display(flag.get("category", ""))
    disposition = flag.get("disposition", DISPOSITION_UNDECIDED)
    ocr = flag.get("ocr_confidence")
    return {
        "id": flag.get("id", ""),
        "category": flag.get("category", ""),
        "element": label,
        "element_description": description,
        "basis": flag.get("basis", ""),
        "basis_label": BASIS_DISPLAY.get(flag.get("basis", ""), flag.get("basis", "")),
        "inferred": flag.get("basis") == FlagBasis.INFERRED.value,
        "extraction_confidence": f"{float(flag.get('extraction_confidence', 0.0)):.2f}",
        "ocr_confidence": "n/a" if ocr is None else f"{float(ocr):.2f}",
        "source_passage": " ".join((flag.get("source_passage") or "").split()),
        "inference_note": flag.get("inference_note", ""),
        "verification_source": flag.get("verification_source"),
        "descriptors": _descriptor_view(flag.get("descriptors") or {}),
        "reference": _reference_context(flag.get("category", ""), reference),
        "disposition": disposition,
        "disposition_label": DISPOSITION_DISPLAY.get(disposition, disposition),
        "disposition_note": flag.get("disposition_note", ""),
        "disposition_at": flag.get("disposition_at", ""),
    }


def _stored_flag_groups(flags: list[dict], reference=None) -> list[dict]:
    """Group persisted case-file flags by category (enum order), each flag enriched."""
    views = [stored_flag_view(f, reference) for f in flags]
    groups: list[dict] = []
    for category in FlagCategory:
        members = [v for v in views if v["category"] == category.value]
        if members:
            groups.append({"label": factor_display(category.value)[0], "flags": members})
    return groups


#: Record-status buckets for the intake worklist. Gap/error need a reviewer to
#: act; acquiring/linking are in flight; linked is ready to review. A gap is a
#: call to action, never a clean result (README v2 §6.6).
_WORKLIST_NEEDS_ATTENTION = frozenset({"NOT_FOUND", "ERROR"})
_WORKLIST_IN_PROGRESS = frozenset({"ACQUIRING", "LINKING", "NOT_STARTED"})


def worklist_row(case_file) -> dict:
    """One submitted case file reduced to the columns the worklist needs."""
    return {
        "case_id": case_file.case_id,
        "name": case_file.name,
        "jurisdiction": case_file.jurisdiction,
        "crime": case_file.crime,
        "conviction_year": case_file.conviction_year,
        "record_status": case_file.record_status,
        "record_status_label": case_file.record_status_label,
        "submitted_at": (case_file.submitted_at or "")[:10],
        "flag_count": case_file.flag_count,
        "open_flag_count": case_file.open_flag_count,
        "linked_record_count": case_file.linked_record_count,
        "is_gap": case_file.record_status == "NOT_FOUND",
        "is_error": case_file.record_status == "ERROR",
    }


def worklist_view(case_files) -> dict:
    """Group submitted intakes into an actionable worklist (newest first).

    Three buckets: ``needs_attention`` (a gap or error the reviewer must resolve,
    e.g. by pasting the record text), ``in_progress`` (records still being
    retrieved), and ``linked`` (a record is attached and its flags are ready to
    review). Nothing here is scored or ranked — it is ordered by workflow state.
    """
    rows = [worklist_row(cf) for cf in case_files]
    needs = [r for r in rows if r["record_status"] in _WORKLIST_NEEDS_ATTENTION]
    progress = [r for r in rows if r["record_status"] in _WORKLIST_IN_PROGRESS]
    linked = [r for r in rows if r["record_status"] == "LINKED"]
    return {
        "needs_attention": needs,
        "in_progress": progress,
        "linked": linked,
        "total": len(rows),
        "counts": {
            "needs_attention": len(needs),
            "in_progress": len(progress),
            "linked": len(linked),
            "open_flags": sum(r["open_flag_count"] for r in linked),
        },
    }


