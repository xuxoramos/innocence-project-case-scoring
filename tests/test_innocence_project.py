"""Tests for the Innocence Project overlay (roster load + conservative match)."""

from __future__ import annotations

import json

from risk_engine.innocence_project import IPCase, load_roster, tag_cases
from risk_engine.store import StoredCase


def _case(name: str, state: str) -> StoredCase:
    return StoredCase(
        provenance="nre_exoneration",
        nre_id=name.replace(" ", "_"),
        name=name,
        state=state,
        county="",
        crime="Robbery",
        crime_year=1990,
        conviction_year=1991,
        matched=True,
    )


def test_load_roster_reads_and_tolerates_missing(tmp_path):
    p = tmp_path / "roster.json"
    p.write_text(
        json.dumps(
            [{"name": "Marvin Anderson", "slug": "marvin-anderson", "state": "Virginia",
              "exoneration_year": "2002"}]
        ),
        encoding="utf-8",
    )
    roster = load_roster(p)
    assert roster == [IPCase("Marvin Anderson", "marvin-anderson", "Virginia", "2002")]
    # A path that does not exist is not an error; the overlay just no-ops.
    assert load_roster(tmp_path / "nope.json") == []


def test_exact_name_and_state_match():
    cases = [_case("Marvin Anderson", "Virginia"), _case("Someone Else", "Texas")]
    n = tag_cases(cases, [IPCase("Marvin Anderson", "marvin-anderson", "Virginia")])
    assert n == 1
    assert cases[0].innocence_project is True
    assert cases[1].innocence_project is False


def test_state_must_agree():
    cases = [_case("Marvin Anderson", "Ohio")]
    assert tag_cases(cases, [IPCase("Marvin Anderson", "m", "Virginia")]) == 0
    assert cases[0].innocence_project is False


def test_surname_initial_fallback_recovers_name_variants():
    # "Ron Williamson" (roster) -> "Ronald Keith Williamson" (store), same state.
    cases = [_case("Ronald Keith Williamson", "Oklahoma")]
    n = tag_cases(cases, [IPCase("Ron Williamson", "ron-williamson", "Oklahoma")])
    assert n == 1
    assert cases[0].innocence_project is True


def test_suffix_is_ignored():
    cases = [_case("Robert Lee Miller Jr.", "Oklahoma")]
    n = tag_cases(cases, [IPCase("Robert Miller", "robert-miller", "Oklahoma")])
    assert n == 1
    assert cases[0].innocence_project is True


def test_ambiguous_surname_is_not_tagged():
    # Two different people share surname+initial+state -> fuzzy pass must skip.
    cases = [_case("James Alan Smith", "Texas"), _case("James Brian Smith", "Texas")]
    n = tag_cases(cases, [IPCase("James Smith", "james-smith", "Texas")])
    assert n == 0
    assert all(c.innocence_project is False for c in cases)


def test_retag_is_idempotent_and_resets():
    cases = [_case("Marvin Anderson", "Virginia")]
    roster = [IPCase("Marvin Anderson", "marvin-anderson", "Virginia")]
    assert tag_cases(cases, roster) == 1
    assert tag_cases(cases, roster) == 1  # stable
    # Re-tagging with an empty roster clears the prior flag.
    assert tag_cases(cases, []) == 0
    assert cases[0].innocence_project is False
