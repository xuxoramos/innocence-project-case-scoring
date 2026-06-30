"""Case packet assembler — the non-ranking deliverable (README v2 Section 7).

A :class:`CasePacket` is what one processed intake produces: a structured intake
summary, the record-retrieval result (with the three distinct states from
Section 6.6 kept separate), and the triggered flags **grouped by category**.
There is no score and no rank anywhere in here. Each flag stands alone with its
own source passage and confidence, and every packet — flagged or not — carries
the standing scope statement so "no flags" is never read as "no problem".
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field

from .intake.record import IntakeRecord
from .intake.schema import IntakeCategory, field_by_key
from .models import SCOPE_STATEMENT, Case, Flag, FlagBasis, FlagCategory


class RecordSearchStatus(str, enum.Enum):
    """The three distinct outcomes of looking for an expected record (6.6).

    ``NOT_FOUND`` (searched, nothing returned) and ``FOUND_NO_FLAGS`` (searched,
    retrieved, but nothing matched a flag category) are deliberately different
    states and must never be visually conflated — a gap in the record is not the
    same as a record that came back clean.
    """

    FOUND_WITH_FLAGS = "found_with_flags"
    FOUND_NO_FLAGS = "found_no_flags"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class RecordSearch:
    """One expected record type and what the retrieval step found for it."""

    record_type: str
    status: RecordSearchStatus
    detail: str = ""  # e.g. document id / location, or why it could not be found


@dataclass
class FlagGroup:
    """All flags of one category. Flags are listed, never combined or summed."""

    category: FlagCategory
    flags: list[Flag] = field(default_factory=list)


@dataclass
class CasePacket:
    """Structured, non-ranking output for one processed intake (Section 7)."""

    case_id: str
    intake: IntakeRecord | None = None
    records: list[RecordSearch] = field(default_factory=list)
    flag_groups: list[FlagGroup] = field(default_factory=list)
    scope_statement: str = SCOPE_STATEMENT

    @property
    def total_flags(self) -> int:
        return sum(len(g.flags) for g in self.flag_groups)

    @property
    def has_flags(self) -> bool:
        return self.total_flags > 0

    def records_with_status(self, status: RecordSearchStatus) -> list[RecordSearch]:
        return [r for r in self.records if r.status is status]

    @property
    def records_not_found(self) -> list[RecordSearch]:
        return self.records_with_status(RecordSearchStatus.NOT_FOUND)

    def render_text(self) -> str:
        """A plain-text rendering of the packet for terminal/console review."""
        lines: list[str] = [f"=== CASE PACKET: {self.case_id} ===", "", self.scope_statement, ""]
        lines += self._render_intake()
        lines += self._render_records()
        lines += self._render_flags()
        return "\n".join(lines)

    def _render_intake(self) -> list[str]:
        out = ["-- Intake Summary --"]
        if self.intake is None:
            out += ["  (no structured intake provided)", ""]
            return out
        any_field = False
        for category in IntakeCategory:
            fields = self.intake.by_category(category)
            if not fields:
                continue
            any_field = True
            out.append(f"  [{category.value}]")
            for item in fields:
                label = field_by_key(item.key).label
                out.append(f"    {label}: {item.value}")
        if not any_field:
            out.append("  (no fields populated)")
        missing = self.intake.missing_near_universal()
        if missing:
            out.append(f"  (near-universal fields still missing: {', '.join(missing)})")
        out.append("")
        return out

    def _render_records(self) -> list[str]:
        out = ["-- Records Searched --"]
        if not self.records:
            out += ["  (no record searches recorded)", ""]
            return out
        for r in self.records:
            detail = f" — {r.detail}" if r.detail else ""
            out.append(f"  [{r.status.value}] {r.record_type}{detail}")
        out.append("")
        return out

    def _render_flags(self) -> list[str]:
        out = ["-- Flags (grouped by category; each stands alone, never combined) --"]
        if not self.has_flags:
            out += [
                "  No elements matched a documented category of concern.",
                "  Per the scope statement above, this is not a finding that the case is sound.",
                "",
            ]
            return out
        for group in self.flag_groups:
            out.append(f"  [{group.category.value}]")
            for flag in group.flags:
                out += _render_flag(flag)
        out.append("")
        return out


def _render_flag(flag: Flag) -> list[str]:
    ocr = "n/a" if flag.ocr_confidence is None else f"{flag.ocr_confidence:.2f}"
    sub = ""
    if flag.basis is FlagBasis.INFERRED:
        sub = " (inferred)"
    elif flag.basis is FlagBasis.DIRECTLY_STATED:
        sub = " (directly stated)"
    passage = " ".join(flag.source_passage.split())
    lines = [f"    -{sub} confidence: extract={flag.extraction_confidence:.2f} ocr={ocr}"]
    if flag.basis is FlagBasis.INFERRED and flag.inference_note:
        lines.append(f"      basis for inference: {flag.inference_note}")
    if flag.verification_source:
        lines.append(f"      verification source: {flag.verification_source}")
    if passage:
        lines.append(f'      "{passage}"')
    return lines


def _group_flags(flags: Iterable[Flag]) -> list[FlagGroup]:
    """Group flags by category in enum-declaration order; skip empty categories."""
    flags = list(flags)
    groups: list[FlagGroup] = []
    for category in FlagCategory:
        members = [f for f in flags if f.category is category]
        if members:
            groups.append(FlagGroup(category=category, flags=members))
    return groups


def assemble_packet(
    *,
    case_id: str,
    intake: IntakeRecord | None = None,
    flags: Iterable[Flag] = (),
    records: Iterable[RecordSearch] = (),
) -> CasePacket:
    """Assemble a :class:`CasePacket` from its parts. Never ranks or scores."""
    return CasePacket(
        case_id=case_id,
        intake=intake,
        records=list(records),
        flag_groups=_group_flags(flags),
    )


def assemble_from_case(
    case: Case,
    *,
    intake: IntakeRecord | None = None,
    records: Iterable[RecordSearch] = (),
) -> CasePacket:
    """Convenience: build a packet from a processed :class:`Case`.

    Pulls ``case_id`` and ``case.flags``. If no explicit ``records`` are given,
    each retrieved document is reported as found; whether it produced flags is a
    case-level approximation (flags are not document-attributed in the POC), so
    a case with any flag marks its documents ``FOUND_WITH_FLAGS`` and an
    unflagged case marks them ``FOUND_NO_FLAGS`` — the gap state (``NOT_FOUND``)
    can only come from an explicit ``records`` list naming an expected type.
    """
    records = list(records)
    if not records:
        status = (
            RecordSearchStatus.FOUND_WITH_FLAGS
            if case.flags
            else RecordSearchStatus.FOUND_NO_FLAGS
        )
        records = [
            RecordSearch(record_type=doc.media_type, status=status, detail=doc.doc_id)
            for doc in case.documents
        ]
    return assemble_packet(
        case_id=case.case_id, intake=intake, flags=case.flags, records=records
    )
