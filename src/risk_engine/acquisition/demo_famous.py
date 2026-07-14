"""Demo acquisition source — real, famous exonerations (real public records).

A *demonstration-only* offline source. Each entry is a **real** exoneree whose
**real, published appellate opinion** (pulled verbatim from CourtListener, a
public-domain court record) names a strongly-discredited forensic method. Unlike
the earlier pseudonymized demo, these use the person's real name: each is a
confirmed, public exoneration, so naming them is accurate and respectful, and
the flagged forensic content is exactly what the real record says.

Each case ships two documents, mirroring what a real intake retrieval pulls
(spec v3 / consultant §4): the **appellate opinion** (the substantive text the
flags are drawn from) and a **trial-court docket** summary (real docket
metadata — court, docket number, parties, charge). The third expected record
type, *post-conviction filings*, is intentionally not provided, so it surfaces
as an honest ``NOT_FOUND`` gap (README v2 §6.6): the tool says out loud what it
did and did not retrieve, and never treats a missing record as a clean bill.

This source never touches the exoneration store or calibration; it exists only
so a reviewer can watch real flags fire against real, recognizable cases during
a demo. It must never be used as training/label data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from ..config import settings
from ..models import Case, Document
from .base import AcquisitionSource, register_source

#: Where the verbatim opinion texts live (public-domain court records).
_OPINION_DIR = settings.data_root / "demo" / "famous"


@dataclass(frozen=True)
class _FamousCase:
    case_id: str
    caption: str  # real case caption; retrieval matches the applicant surname here
    year: int  # approximate conviction year (soft corroboration only)
    case_type: str
    opinion_file: str  # verbatim opinion text file under _OPINION_DIR
    docket_text: str  # real trial-court docket metadata summary
    citation: str  # operator reference; shown as the opinion's verification detail


#: Three real, publicly documented exonerations, each with a digitized opinion
#: in CourtListener whose text the flagging pipeline independently fires on.
_FAMOUS_CASES: tuple[_FamousCase, ...] = (
    _FamousCase(
        case_id="FAMOUS-HARWARD",
        caption="Harward v. Commonwealth",
        year=1986,
        case_type="homicide",
        opinion_file="harward_opinion.txt",
        docket_text=(
            "COURT OF APPEALS OF VIRGINIA. Record No. 0323-86-1. "
            "Harward v. Commonwealth, 364 S.E.2d 511 (1988). Appeal from the "
            "Circuit Court of the City of Newport News. Charge: first-degree "
            "murder. Panel: Baker, Coleman, and Hodges, JJ. Disposition: "
            "conviction affirmed on this appeal."
        ),
        citation="Harward v. Commonwealth, 364 S.E.2d 511 (Va. Ct. App. 1988)",
    ),
    _FamousCase(
        case_id="FAMOUS-HUFFINGTON",
        caption="Huffington v. Nuth",
        year=1981,
        case_type="homicide",
        opinion_file="huffington_opinion.txt",
        docket_text=(
            "UNITED STATES COURT OF APPEALS FOR THE FOURTH CIRCUIT. "
            "Huffington v. Nuth, 140 F.3d 572 (4th Cir. 1998). Federal habeas "
            "corpus review of Maryland first-degree murder convictions "
            "(Harford County, 1981). Panel: Murnaghan, Niemeyer, and Motz, JJ. "
            "Disposition: denial of relief affirmed."
        ),
        citation="Huffington v. Nuth, 140 F.3d 572 (4th Cir. 1998)",
    ),
    _FamousCase(
        case_id="FAMOUS-CHMIEL",
        caption="Commonwealth v. Chmiel",
        year=1983,
        case_type="homicide",
        opinion_file="chmiel_opinion.txt",
        docket_text=(
            "SUPREME COURT OF PENNSYLVANIA. No. 780 CAP. Commonwealth v. "
            "Chmiel. Appeal from the Order of the Court of Common Pleas of "
            "Lackawanna County at No. CP-35-CR-0000748-1983. Capital "
            "post-conviction (PCRA) proceeding. Decided 2020."
        ),
        citation="Commonwealth v. Chmiel, No. 780 CAP (Pa. 2020)",
    ),
)


@lru_cache(maxsize=None)
def _load_opinion(filename: str) -> str:
    """Read a verbatim opinion text file (cached; missing file -> empty text)."""
    path = _OPINION_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


class DemoFamousSource(AcquisitionSource):
    """Offline demo source of real, famous exonerations with real opinion text."""

    jurisdiction = "demo_famous"
    display_name = "Demo — famous exonerations (real records, offline)"
    offline = True

    def __init__(self) -> None:
        self._by_id = {c.case_id: c for c in _FAMOUS_CASES}

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = _FAMOUS_CASES if limit is None else _FAMOUS_CASES[:limit]
        for row in rows:
            yield Case(
                case_id=row.case_id,
                jurisdiction=self.jurisdiction,
                year=row.year,
                case_type=row.case_type,
                features={"_cl_case_name": row.caption},
            )

    def fetch(self, case: Case) -> Case:
        row = self._by_id.get(case.case_id)
        if row is None or case.documents:
            return case
        opinion = _load_opinion(row.opinion_file)
        # The appellate opinion — the substantive text the flags are drawn from.
        case.documents.append(
            Document(
                doc_id=f"{case.case_id}-OPINION",
                case_id=case.case_id,
                source_uri=f"demo-record://{self.jurisdiction}/{case.case_id}/opinion",
                media_type="text/plain",
                needs_ocr=False,
                normalized_text=opinion,
                metadata={
                    "demo_only": True,
                    "record_type": "appellate opinion",
                    "citation": row.citation,
                },
            )
        )
        # The trial-court docket — real docket metadata, shown as a retrieved
        # record alongside the opinion (consultant §4: docket + opinion).
        case.documents.append(
            Document(
                doc_id=f"{case.case_id}-DOCKET",
                case_id=case.case_id,
                source_uri=f"demo-record://{self.jurisdiction}/{case.case_id}/docket",
                media_type="text/plain",
                needs_ocr=False,
                normalized_text=row.docket_text,
                metadata={"demo_only": True, "record_type": "trial court docket"},
            )
        )
        return case


register_source(DemoFamousSource())
