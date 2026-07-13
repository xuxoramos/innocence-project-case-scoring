"""Unit tests for the anchor + modifier + word-window matcher (spec v3 item 1)."""

from __future__ import annotations

from risk_engine.matching import find_windowed

_ANCHORS = frozenset({"informant", "snitch"})
_MODS = frozenset({"testified", "deal", "leniency"})


def test_hit_when_anchor_and_modifier_within_window():
    span = find_windowed("The snitch testified for the state.", _ANCHORS, _MODS, window=6)
    assert span is not None
    # Span points at the anchor token so callers can quote its sentence.
    text = "The snitch testified for the state."
    assert text[span[0] : span[1]] == "snitch"


def test_no_hit_when_modifier_outside_window():
    text = "The snitch walked a very long way before anyone ever heard him testified"
    assert find_windowed(text, _ANCHORS, _MODS, window=3) is None


def test_no_hit_without_anchor():
    assert find_windowed("The witness testified for the state.", _ANCHORS, _MODS, window=6) is None


def test_no_hit_without_modifier():
    assert find_windowed("The informant lived in the city.", _ANCHORS, _MODS, window=6) is None


def test_first_qualifying_anchor_wins():
    text = "An informant here. Later a snitch got a deal."
    span = find_windowed(text, _ANCHORS, _MODS, window=3)
    # The first anchor has no nearby modifier; the second (snitch ... deal) does.
    assert text[span[0] : span[1]] == "snitch"


def test_hyphenated_token_stays_whole():
    span = find_windowed(
        "The co-defendant testified.", frozenset({"co-defendant"}), frozenset({"testified"}), 4
    )
    assert span is not None
