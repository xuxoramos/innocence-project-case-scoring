"""Tests for the async record-acquisition job (spec v3 point 2)."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from risk_engine import casework
from risk_engine.acquisition import register_source
from risk_engine.acquisition.base import AcquisitionSource
from risk_engine.casefiles import (
    RECORD_STATUS_ERROR,
    RECORD_STATUS_LINKED,
    RECORD_STATUS_NOT_FOUND,
    case_file_from_intake,
    load_case_files,
    save_case_files,
    update_case_file,
)
from risk_engine.casework import _status_from_records, run_retrieval_job
from risk_engine.intake.record import IntakeRecord
from risk_engine.models import Case, Document
from risk_engine.packet import RecordSearch, RecordSearchStatus
from risk_engine.processing import default_pipeline


class _FakeSource(AcquisitionSource):
    """Offline source with one matchable caption, so the job runs without network."""

    jurisdiction = "casework_test_src"
    display_name = "Casework Test Source"

    _DATA = [
        (
            "Commonwealth v. Doswell",
            1986,
            "The sole eyewitness identified him at trial; bite-mark comparison was used.",
        ),
        ("Commonwealth v. Unrelated", 1990, "An ordinary appeal with nothing notable."),
    ]

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = self._DATA if limit is None else self._DATA[:limit]
        for i, (caption, year, text) in enumerate(rows):
            case = Case(case_id=f"CW-{i}", jurisdiction=self.jurisdiction, year=year)
            case.features["_cl_case_name"] = caption
            case.features["_text"] = text
            yield case

    def fetch(self, case: Case) -> Case:
        if not case.documents:
            case.documents.append(
                Document(
                    doc_id=f"{case.case_id}-OP",
                    case_id=case.case_id,
                    source_uri="https://example/opinions/1/",
                    media_type="text/plain",
                    needs_ocr=False,
                    normalized_text=case.features.get("_text", ""),
                )
            )
        return case


register_source(_FakeSource())


def _intake(name: str = "Thomas Doswell") -> IntakeRecord:
    rec = IntakeRecord(applicant_ref="APP-1")
    rec.set("applicant_full_name", name)
    rec.set("date_of_conviction", "March 1986")
    return rec


def _saved(tmp_path, name: str = "Thomas Doswell"):
    intake = _intake(name)
    case_file = case_file_from_intake(intake)
    path = tmp_path / "app.db"
    save_case_files([case_file], path)
    return case_file, intake, path


# --- status helper ----------------------------------------------------------


def test_status_from_records_linked_when_any_found():
    records = [
        RecordSearch("appellate opinion", RecordSearchStatus.FOUND_WITH_FLAGS),
        RecordSearch("trial court docket", RecordSearchStatus.NOT_FOUND),
    ]
    assert _status_from_records(records) == RECORD_STATUS_LINKED


def test_status_from_records_not_found_when_all_gaps():
    records = [
        RecordSearch("appellate opinion", RecordSearchStatus.NOT_FOUND),
        RecordSearch("trial court docket", RecordSearchStatus.NOT_FOUND),
    ]
    assert _status_from_records(records) == RECORD_STATUS_NOT_FOUND


# --- run_retrieval_job (offline, tmp store) ---------------------------------


def test_run_retrieval_job_links_matching_records(tmp_path):
    case_file, intake, path = _saved(tmp_path)
    status = run_retrieval_job(
        case_file.case_id,
        intake,
        source_key="casework_test_src",
        db_path=path,
        pipeline=default_pipeline(),
    )
    assert status == RECORD_STATUS_LINKED

    [reloaded] = load_case_files(path)
    assert reloaded.record_status == RECORD_STATUS_LINKED
    assert reloaded.retrieved_at  # stamped
    assert reloaded.retrieval_error == ""
    # the appellate opinion was linked and carried flags; the two unreachable
    # record types are honest gaps, never conflated with "clean" (§6.6)
    by_type = {r["record_type"]: r["status"] for r in reloaded.record_searches}
    assert by_type["appellate opinion"] == "found_with_flags"
    assert by_type["trial court docket"] == "not_found"
    assert reloaded.linked_record_count == 1


def test_run_retrieval_job_gap_is_not_found(tmp_path):
    case_file, intake, path = _saved(tmp_path, name="Someone Notinthere")
    status = run_retrieval_job(
        case_file.case_id,
        intake,
        source_key="casework_test_src",
        db_path=path,
        pipeline=default_pipeline(),
    )
    assert status == RECORD_STATUS_NOT_FOUND

    [reloaded] = load_case_files(path)
    assert reloaded.record_status == RECORD_STATUS_NOT_FOUND
    assert reloaded.retrieved_at
    assert all(r["status"] == "not_found" for r in reloaded.record_searches)
    assert reloaded.linked_record_count == 0


def test_run_retrieval_job_captures_error(tmp_path, monkeypatch):
    case_file, intake, path = _saved(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("source unreachable")

    monkeypatch.setattr(casework, "build_packet_for_intake", _boom)
    status = run_retrieval_job(
        case_file.case_id, intake, source_key="casework_test_src", db_path=path
    )
    assert status == RECORD_STATUS_ERROR

    [reloaded] = load_case_files(path)
    assert reloaded.record_status == RECORD_STATUS_ERROR
    assert "source unreachable" in reloaded.retrieval_error
    assert reloaded.record_searches == []


# --- update_case_file guards ------------------------------------------------


def test_update_case_file_updates_matching_row(tmp_path):
    case_file, _intake_rec, path = _saved(tmp_path)
    updated = update_case_file(case_file.case_id, db_path=path, record_status="LINKING")
    assert updated is not None
    assert load_case_files(path)[0].record_status == "LINKING"


def test_update_case_file_missing_returns_none(tmp_path):
    _saved(tmp_path)
    path = tmp_path / "app.db"
    assert update_case_file("CF-nope", db_path=path, record_status="LINKING") is None


def test_update_case_file_rejects_unknown_field(tmp_path):
    case_file, _intake_rec, path = _saved(tmp_path)
    with pytest.raises(ValueError):
        update_case_file(case_file.case_id, db_path=path, bogus="x")
