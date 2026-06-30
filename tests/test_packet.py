"""Tests for the non-ranking case packet assembler (README v2 Section 7)."""

from __future__ import annotations

from risk_engine.intake.record import IntakeRecord
from risk_engine.models import SCOPE_STATEMENT, Case, Document, Flag, FlagBasis, FlagCategory
from risk_engine.packet import (
    CasePacket,
    RecordSearch,
    RecordSearchStatus,
    assemble_from_case,
    assemble_packet,
)


def _flag(category, basis=FlagBasis.DIRECTLY_STATED, passage="x", conf=0.8):
    return Flag(
        category=category,
        basis=basis,
        extraction_confidence=conf,
        source_passage=passage,
    )


def test_flags_grouped_by_category_in_enum_order():
    flags = [
        _flag(FlagCategory.EVIDENCE_PRESERVATION),
        _flag(FlagCategory.DISCREDITED_FORENSIC_METHOD),
        _flag(FlagCategory.DISCREDITED_FORENSIC_METHOD),
    ]
    packet = assemble_packet(case_id="C1", flags=flags)
    cats = [g.category for g in packet.flag_groups]
    # forensic comes before evidence_preservation in the enum declaration
    assert cats == [FlagCategory.DISCREDITED_FORENSIC_METHOD, FlagCategory.EVIDENCE_PRESERVATION]
    assert len(packet.flag_groups[0].flags) == 2
    assert packet.total_flags == 3


def test_empty_packet_has_no_flags_but_keeps_scope_statement():
    packet = assemble_packet(case_id="C2")
    assert not packet.has_flags
    assert packet.total_flags == 0
    assert packet.scope_statement == SCOPE_STATEMENT
    text = packet.render_text()
    assert "No elements matched a documented category" in text
    assert "not a finding that the case is sound" in text
    assert SCOPE_STATEMENT in text


def test_record_states_are_kept_distinct():
    records = [
        RecordSearch("trial transcript", RecordSearchStatus.FOUND_WITH_FLAGS, "doc-1"),
        RecordSearch("police report", RecordSearchStatus.NOT_FOUND),
        RecordSearch("docket sheet", RecordSearchStatus.FOUND_NO_FLAGS, "doc-2"),
    ]
    packet = assemble_packet(case_id="C3", records=records)
    assert len(packet.records_not_found) == 1
    assert packet.records_not_found[0].record_type == "police report"
    text = packet.render_text()
    # not-found and found-no-flags must be visually different states
    assert "[not_found] police report" in text
    assert "[found_no_flags] docket sheet" in text


def test_inferred_flag_shows_subcategory_and_basis_note():
    flag = Flag(
        category=FlagCategory.WITNESS_ID_CIRCUMSTANCE,
        basis=FlagBasis.INFERRED,
        extraction_confidence=0.7,
        source_passage="victim and defendant of different races",
        inference_note="races inferred from named demographic fields",
    )
    packet = assemble_packet(case_id="C4", flags=[flag])
    text = packet.render_text()
    assert "(inferred)" in text
    assert "basis for inference: races inferred" in text


def test_intake_summary_rendered_by_category():
    rec = IntakeRecord(applicant_ref="A1", chapter="PA")
    rec.set("applicant_full_name", "John Doe", extraction_confidence=0.95)
    packet = assemble_packet(case_id="C5", intake=rec)
    text = packet.render_text()
    assert "-- Intake Summary --" in text
    assert "John Doe" in text


def test_assemble_from_case_derives_record_states():
    case = Case(case_id="K1", jurisdiction="allegheny_pa")
    case.documents.append(Document(doc_id="K1-1", case_id="K1", media_type="text/plain"))
    case.flags.append(_flag(FlagCategory.WITNESS_ID_CIRCUMSTANCE))
    packet = assemble_from_case(case)
    assert isinstance(packet, CasePacket)
    assert packet.records[0].status is RecordSearchStatus.FOUND_WITH_FLAGS

    clean = Case(case_id="K2", jurisdiction="allegheny_pa")
    clean.documents.append(Document(doc_id="K2-1", case_id="K2"))
    clean_packet = assemble_from_case(clean)
    assert clean_packet.records[0].status is RecordSearchStatus.FOUND_NO_FLAGS


def test_explicit_records_override_derivation():
    case = Case(case_id="K3", jurisdiction="allegheny_pa")
    case.documents.append(Document(doc_id="K3-1", case_id="K3"))
    records = [RecordSearch("police report", RecordSearchStatus.NOT_FOUND)]
    packet = assemble_from_case(case, records=records)
    assert packet.records == records
