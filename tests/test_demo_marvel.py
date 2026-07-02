"""Demo-only 'demo_marvel' de-identified record source.

Verifies that each pseudonymized fixture, driven by its matching intake payload,
retrieves its record and fires the expected DISCREDITED_FORENSIC_METHOD flag —
the exact path a reviewer exercises in the demo. This guards the demo against
silent breakage (a renamed caption, a lexicon change) and confirms no real
defendant identity leaks into the pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from risk_engine.acquisition import get_source, list_sources
from risk_engine.intake.record import IntakeRecord
from risk_engine.models import FlagCategory
from risk_engine.retrieval import build_packet_for_intake

_PAYLOADS = Path(__file__).resolve().parents[1] / "data" / "demo" / "marvel_intakes.json"


def _intake_from_fields(fields: dict[str, str]) -> IntakeRecord:
    rec = IntakeRecord(applicant_ref="demo")
    for key, value in fields.items():
        rec.set(key, value)
    return rec


def _load_payloads() -> list[dict]:
    return json.loads(_PAYLOADS.read_text())["intakes"]


def test_demo_source_registered() -> None:
    assert "demo_marvel" in list_sources()
    assert get_source("demo_marvel").display_name


@pytest.mark.parametrize(
    ("alias", "expected_method_fragment"),
    [
        ("Peter Parker", "microscopic hair comparison"),
        ("Anthony Stark", "bite-mark comparison"),
        ("Steven Rogers", "microscopic hair comparison"),
    ],
)
def test_demo_intake_fires_forensic_flag(alias: str, expected_method_fragment: str) -> None:
    payload = next(p for p in _load_payloads() if p["fields"]["applicant_full_name"] == alias)
    intake = _intake_from_fields(payload["fields"])

    packet = build_packet_for_intake(intake, source_key="demo_marvel")

    forensic = [
        f
        for g in packet.flag_groups
        if g.category is FlagCategory.DISCREDITED_FORENSIC_METHOD
        for f in g.flags
    ]
    assert forensic, f"expected a discredited-forensic flag for {alias}"
    assert any(expected_method_fragment in (f.verification_source or "") for f in forensic)
    # Tier A methods carry the discreditation-tier descriptor.
    assert any(f.descriptors.get("discreditation_tier") == "A" for f in forensic)


def test_demo_payloads_match_fixture_captions() -> None:
    """Every payload alias resolves to exactly one fixture record (no leakage)."""
    for payload in _load_payloads():
        intake = _intake_from_fields(payload["fields"])
        packet = build_packet_for_intake(intake, source_key="demo_marvel")
        assert packet.total_flags, (
            f"no record matched for {payload['fields']['applicant_full_name']}"
        )
