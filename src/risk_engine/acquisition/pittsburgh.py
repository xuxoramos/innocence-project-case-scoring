"""Allegheny County (Pittsburgh) acquisition source — POC starting point.

Scope (README 4): pre-2000 homicide/sexual-assault convictions from public
court records. Real docket/transcript scraping is intentionally left as a
clearly marked TODO; this stub provides the seam and a small fixture so the
rest of the pipeline and the UI are testable end to end.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Case, Document
from .base import AcquisitionSource, register_source

# Small built-in fixture so discovery returns something during the POC. Replace
# with live docket enumeration once the chapter approves data handling.
_FIXTURE = [
    {"case_id": "ALL-1987-0042", "year": 1987, "case_type": "homicide"},
    {"case_id": "ALL-1992-0311", "year": 1992, "case_type": "sexual_assault"},
]


class AlleghenyCountySource(AcquisitionSource):
    jurisdiction = "allegheny_pa"
    display_name = "Allegheny County, PA (Pittsburgh)"

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = _FIXTURE if limit is None else _FIXTURE[:limit]
        for row in rows:
            yield Case(jurisdiction=self.jurisdiction, **row)

    def fetch(self, case: Case) -> Case:
        # TODO: download dockets/transcripts from the public records portal.
        if not case.documents:
            case.documents.append(
                Document(
                    doc_id=f"{case.case_id}-D1",
                    case_id=case.case_id,
                    source_uri=f"public-record://{self.jurisdiction}/{case.case_id}",
                    needs_ocr=True,
                )
            )
        return case


register_source(AlleghenyCountySource())
