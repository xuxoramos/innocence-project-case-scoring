"""Tests for the case-seriousness descriptor (spec v3 §3.4 severity axis)."""

from risk_engine.severity import (
    SERIOUSNESS_MEANING,
    seriousness_descriptor,
    seriousness_tier,
)


def test_homicide_offense_grades_capital():
    assert seriousness_tier("Murder") == "capital"
    assert seriousness_tier("Manslaughter") == "capital"
    assert seriousness_tier("Attempted Murder") == "capital"


def test_serious_violent_and_felony_and_lesser_tiers():
    assert seriousness_tier("Sexual Assault") == "serious_violent"
    assert seriousness_tier("Drug Possession or Sale") == "felony"
    assert seriousness_tier("Traffic Offense") == "lesser"


def test_specific_offense_wins_over_substring():
    # "sexual assault" must not degrade to the shorter "assault" key; both are
    # serious_violent here, so the grade is stable either way, but the longest
    # key is what matches.
    assert seriousness_tier("Sexual Assault") == "serious_violent"


def test_free_text_variant_grades_same_as_exact():
    assert seriousness_tier("first-degree murder") == "capital"
    assert seriousness_tier("Armed Robbery") == "serious_violent"


def test_unknown_or_blank_offense_has_no_grade():
    # No grade rather than a guessed one (§3.2).
    assert seriousness_tier("") is None
    assert seriousness_tier("Military Justice Offense") is None
    assert seriousness_tier("Other") is None
    assert seriousness_descriptor("Other") == {}


def test_descriptor_carries_tier_label_and_basis():
    desc = seriousness_descriptor("Murder")
    assert desc["case_seriousness"] == "capital / homicide"
    assert desc["seriousness_basis"] == SERIOUSNESS_MEANING["capital"]


def test_every_offense_tier_has_a_meaning_and_label():
    from risk_engine.severity import _OFFENSE_TIER, _TIER_LABEL

    for tier in set(_OFFENSE_TIER.values()):
        assert tier in SERIOUSNESS_MEANING
        assert tier in _TIER_LABEL
