"""Async record-acquisition job: intake -> retrieval -> linked records on a case file.

This is spec v3 point 2. When a reviewer saves an intake, the case file appears in
the list immediately at ``record_status=ACQUIRING`` and this job runs in the
background: it drives the file through ``LINKING``, retrieves the public court
records that match the applicant (:func:`risk_engine.retrieval.build_packet_for_intake`),
persists the record-search outcomes, and lands on a terminal status.

The lifecycle stays honest per README v2 §6.6: a case that searched and linked no
record ends at ``NOT_FOUND`` (a gap), never conflated with a clean result, and a
retrieval failure ends at ``ERROR`` rather than pretending nothing was there.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from .calibration import calibrated_pipeline
from .casefiles import (
    DEFAULT_DB_PATH,
    RECORD_STATUS_ERROR,
    RECORD_STATUS_LINKED,
    RECORD_STATUS_LINKING,
    RECORD_STATUS_NOT_FOUND,
    update_case_file,
)
from .intake.record import IntakeRecord
from .packet import RecordSearch, RecordSearchStatus
from .processing import Pipeline
from .retrieval import build_packet_for_intake


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _status_from_records(records: list[RecordSearch]) -> str:
    """Terminal status for a completed retrieval (§6.6).

    Any record type that returned a document means at least one record was linked
    (``LINKED``); if every expected type came back empty, that is an honest gap
    (``NOT_FOUND``), not a clean result.
    """
    linked = any(r.status is not RecordSearchStatus.NOT_FOUND for r in records)
    return RECORD_STATUS_LINKED if linked else RECORD_STATUS_NOT_FOUND


def _serialize_records(records: list[RecordSearch]) -> list[dict]:
    return [
        {"record_type": r.record_type, "status": r.status.value, "detail": r.detail}
        for r in records
    ]


def run_retrieval_job(
    case_id: str,
    intake: IntakeRecord,
    *,
    source_key: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    pipeline: Pipeline | None = None,
) -> str:
    """Retrieve and link court records for one saved case file (runs to completion).

    Marks the file ``LINKING``, runs the Section 5 flow, persists the resulting
    record searches, and sets a terminal ``record_status``. Returns the terminal
    status. Any retrieval error is captured on the file (``ERROR``) rather than
    raised, so a background caller never crashes silently.
    """
    update_case_file(case_id, db_path=db_path, record_status=RECORD_STATUS_LINKING)
    try:
        packet = build_packet_for_intake(
            intake,
            source_key=source_key,
            pipeline=pipeline or calibrated_pipeline(),
            case_id=case_id,
        )
    except Exception as exc:  # network/source errors are captured, not raised
        update_case_file(
            case_id,
            db_path=db_path,
            record_status=RECORD_STATUS_ERROR,
            retrieval_error=str(exc),
            retrieved_at=_now(),
        )
        return RECORD_STATUS_ERROR

    status = _status_from_records(packet.records)
    update_case_file(
        case_id,
        db_path=db_path,
        record_status=status,
        record_searches=_serialize_records(packet.records),
        retrieval_error="",
        retrieved_at=_now(),
    )
    return status


def start_retrieval(
    case_id: str,
    intake: IntakeRecord,
    *,
    source_key: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> threading.Thread:
    """Kick off :func:`run_retrieval_job` on a daemon thread and return at once.

    The case file is already persisted (at ``ACQUIRING``) by the caller, so the
    reviewer sees it in the list immediately while records are fetched.
    """
    thread = threading.Thread(
        target=run_retrieval_job,
        args=(case_id, intake),
        kwargs={"source_key": source_key, "db_path": db_path},
        daemon=True,
    )
    thread.start()
    return thread
