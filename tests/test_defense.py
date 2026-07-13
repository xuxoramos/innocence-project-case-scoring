"""Trial-defense-strategy note (spec v3 §10 item 11, reframed)."""

from __future__ import annotations

from risk_engine.defense import defense_strategy_note
from risk_engine.intake.record import IntakeRecord
from risk_engine.retrieval import packet_from_pasted_text


def test_self_defense_yields_a_note():
    note = defense_strategy_note("The defendant argued self-defense at trial.")
    assert note is not None
    assert "self-defense" in note
    assert "concedes the act" in note


def test_consent_yields_a_note():
    assert defense_strategy_note("The defense was consent; he claimed the encounter was consensual.")


def test_no_conceding_strategy_yields_none():
    assert defense_strategy_note("The defense was an alibi supported by three witnesses.") is None
    assert defense_strategy_note("") is None


def test_note_is_never_a_flag_or_score():
    # A pure self-defense record produces a NOTE, not a flag (§3.1 no scoring).
    intake = IntakeRecord(applicant_ref="x")
    text = (
        "The defendant testified that he acted in self-defense during the "
        "altercation. " + ("procedural sentence. " * 40)
    )
    packet = packet_from_pasted_text(intake, text, case_id="CF-x")
    assert packet.notes and any("self-defense" in n for n in packet.notes)
    assert packet.total_flags == 0  # note only, no fabricated flag
    # The note surfaces in the plain-text rendering under a descriptive heading.
    rendered = packet.render_text()
    assert "Notes (descriptive; not flags, not scored)" in rendered
