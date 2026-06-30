"""Tests for the NRE reference loader (real full-CSV schema)."""

from __future__ import annotations

from risk_engine.labels import (
    ExonerationRecord,
    load_known_exonerations,
)
from risk_engine.models import FlagCategory

# Minimal subset of the real NRE "fullcsv.csv" columns.
_HEADER = (
    "ID,Name,State,County of Crime,Worst Crime Display,Date of 1st Convic,"
    "Date of Crime Year,False Confession,False or Misleading Forensic Evidence,"
    "Inadequate Legal Defense,Mistaken Witness ID,Official Misconduct,"
    "Perjury or False Accusation?,DNA,Mistaken Cross-group ID?"
)
_ROWS = [
    # Allegheny murder: MWID + forensic + cross-group.
    "1,John Doe,Pennsylvania,Allegheny,Murder,1987-03-02,1986,No,Yes,No,Yes,No,No,No,Yes",
    # Philadelphia sexual assault: DNA only.
    "2,Jane Roe,Pennsylvania,Philadelphia,Sexual Assault,1992-01-01,1991,No,No,No,No,No,No,Yes,No",
    # Ohio murder: false confession only (unmapped factor).
    "3,Sam Smith,Ohio,Cuyahoga,Murder,1990-06-06,1989,Yes,No,No,No,No,No,No,No",
]


def _write_csv(tmp_path):
    path = tmp_path / "fullcsv.csv"
    path.write_text(_HEADER + "\n" + "\n".join(_ROWS) + "\n", encoding="utf-8")
    return path


def test_load_filters_by_state_and_county(tmp_path):
    path = _write_csv(tmp_path)
    allegheny = load_known_exonerations(path, state="Pennsylvania", county="Allegheny")
    assert len(allegheny) == 1
    rec = allegheny[0]
    assert rec.name == "John Doe"
    assert rec.nre_id == "1"
    assert rec.conviction_year == 1987
    assert rec.crime_year == 1986


def test_factor_columns_map_to_categories(tmp_path):
    path = _write_csv(tmp_path)
    rec = load_known_exonerations(path, state="Pennsylvania", county="Allegheny")[0]
    assert rec.factors == {
        "False or Misleading Forensic Evidence",
        "Mistaken Witness ID",
        "Mistaken Cross-group ID?",
    }
    # Both witness columns collapse to one v2 category.
    assert rec.categories() == {
        FlagCategory.DISCREDITED_FORENSIC_METHOD,
        FlagCategory.WITNESS_ID_CIRCUMSTANCE,
    }


def test_unmapped_factor_recorded_but_no_category(tmp_path):
    path = _write_csv(tmp_path)
    ohio = load_known_exonerations(path, state="Ohio")[0]
    assert ohio.factors == {"False Confession"}
    assert ohio.categories() == set()


def test_load_all_when_unfiltered(tmp_path):
    path = _write_csv(tmp_path)
    assert len(load_known_exonerations(path)) == 3


def test_record_default_factors_empty():
    assert ExonerationRecord(name="A B").categories() == set()
