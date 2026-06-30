"""Tests for the named-official registry and step."""

from __future__ import annotations

import json

import pytest

from risk_engine.models import Case, Document, FlagBasis, FlagCategory
from risk_engine.officials import (
    NamedOfficialRegistry,
    OfficialRecord,
    category_for_role,
)
from risk_engine.processing.officials import NamedOfficialStep


def _record(**kw) -> OfficialRecord:
    base = dict(
        name="Jane Q. Example",
        role="prosecutor",
        finding="withheld exculpatory evidence",
        source="State Bar Disciplinary Board, No. 0000 (fictional)",
    )
    base.update(kw)
    return OfficialRecord(**base)


def test_record_requires_name_and_source():
    with pytest.raises(ValueError):
        _record(name="  ")
    with pytest.raises(ValueError):
        _record(source="")


def test_citation_includes_role_finding_and_source():
    citation = _record().citation
    assert "prosecutor" in citation
    assert "withheld exculpatory evidence" in citation
    assert "Disciplinary Board" in citation


def test_registry_matches_name_and_alias():
    registry = NamedOfficialRegistry.from_records(
        [_record(name="Jane Q. Example", aliases=("J. Example",))]
    )
    assert len(registry) == 1
    matches = registry.match("The trial was prosecuted by J. Example in 1991.")
    assert len(matches) == 1
    assert matches[0].record.name == "Jane Q. Example"


def test_registry_one_hit_per_official():
    registry = NamedOfficialRegistry.from_records([_record()])
    matches = registry.match("Jane Q. Example argued. Later, Jane Q. Example appealed.")
    assert len(matches) == 1


def test_from_dir_missing_directory_is_empty(tmp_path):
    registry = NamedOfficialRegistry.from_dir(tmp_path / "does-not-exist")
    assert len(registry) == 0


def test_from_dir_skips_underscore_files(tmp_path):
    (tmp_path / "_template.json").write_text(
        json.dumps([{"name": "Skip Me", "source": "x"}]), encoding="utf-8"
    )
    (tmp_path / "real.json").write_text(
        json.dumps(
            [
                {
                    "name": "Real Person",
                    "role": "judge",
                    "finding": "judicial misconduct",
                    "source": "Court of Judicial Discipline (fictional)",
                }
            ]
        ),
        encoding="utf-8",
    )
    registry = NamedOfficialRegistry.from_dir(tmp_path)
    assert [r.name for r in registry.records] == ["Real Person"]


def test_empty_registry_step_does_not_apply():
    case = Case(case_id="O", jurisdiction="j")
    case.documents.append(
        Document(doc_id="O1", case_id="O", needs_ocr=False, normalized_text="Jane Q. Example")
    )
    step = NamedOfficialStep(registry=NamedOfficialRegistry.from_records([]))
    assert step.applies_to(case) is False


def test_step_emits_flag_with_citation():
    registry = NamedOfficialRegistry.from_records([_record()])
    case = Case(case_id="O", jurisdiction="j")
    case.documents.append(
        Document(
            doc_id="O1",
            case_id="O",
            needs_ocr=False,
            normalized_text="The case was tried by Jane Q. Example for the state.",
        )
    )
    case = NamedOfficialStep(registry=registry).run(case)
    flags = [f for f in case.flags if f.category is FlagCategory.PROSECUTOR_MISCONDUCT]
    assert len(flags) == 1
    flag = flags[0]
    assert flag.basis is FlagBasis.DIRECTLY_STATED
    assert flag.verification_source == _record().citation
    assert "Jane Q. Example" in flag.source_passage


@pytest.mark.parametrize(
    "role, expected",
    [
        ("prosecutor", FlagCategory.PROSECUTOR_MISCONDUCT),
        ("Assistant District Attorney", FlagCategory.PROSECUTOR_MISCONDUCT),
        ("trial judge", FlagCategory.JUDICIAL_MISCONDUCT),
        ("Detective", FlagCategory.POLICE_MISCONDUCT),
        ("forensic analyst", FlagCategory.EXPERT_WITNESS_MISCONDUCT),
        ("medical examiner", FlagCategory.EXPERT_WITNESS_MISCONDUCT),
        ("court reporter", None),
        ("", None),
    ],
)
def test_category_for_role(role, expected):
    assert category_for_role(role) is expected


def test_step_skips_unclassifiable_role():
    registry = NamedOfficialRegistry.from_records([_record(role="court reporter")])
    case = Case(case_id="O", jurisdiction="j")
    case.documents.append(
        Document(
            doc_id="O1",
            case_id="O",
            needs_ocr=False,
            normalized_text="The case was tried by Jane Q. Example for the state.",
        )
    )
    case = NamedOfficialStep(registry=registry).run(case)
    assert case.flags == []
