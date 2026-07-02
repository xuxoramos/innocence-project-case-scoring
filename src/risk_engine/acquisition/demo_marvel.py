"""Demo acquisition source — de-identified real public cases (Marvel aliases).

This is a *demonstration-only* offline source. Each entry is a real, published
appellate opinion that names a strongly-discredited forensic method, but the
defendant's identity has been consistently pseudonymized to a Marvel character's
civilian name in both the caption and the opinion body. Nothing else about the
forensic content is altered: the discredited method, the way the record
describes it, and the independent scientific basis for the flag are all
unchanged, so every flag the pipeline emits is still verifiable against the
case-independent forensic literature (README v2 Section 5.2).

Why pseudonymize at the *record* layer rather than at intake: retrieval matches
an applicant to a record on name (see :mod:`risk_engine.retrieval`), so the name
is the lookup key. Swapping the name here — and using the same alias on the
intake form — lets the whole intake -> retrieval -> flag flow run end to end
without ever exposing the real person, while keeping the flagged content real.

This source deliberately does NOT touch the exoneration store or calibration; it
exists only so a reviewer can watch a real DISCREDITED_FORENSIC_METHOD flag fire
against a novel case during a demo. It must never be used as training/label data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..models import Case, Document
from .base import AcquisitionSource, register_source


@dataclass(frozen=True)
class _DemoCase:
    case_id: str
    caption: str  # pseudonymized case caption used for name matching
    year: int  # approximate conviction year (soft corroboration only)
    case_type: str
    opinion_text: str  # de-identified opinion excerpt (real forensic content)
    real_citation: str  # for operator reference only; never shown by the UI


# Each opinion excerpt below is faithful to the real published record it is drawn
# from (the discredited method, and how the court/record describes it), with the
# defendant's name swapped to a Marvel civilian alias throughout. The excerpts
# describe what the record says ("contends", "asserts") and assert nothing about
# guilt or innocence (README v2 Sections 3.2 / 6.5).
_DEMO_CASES: tuple[_DemoCase, ...] = (
    _DemoCase(
        case_id="DEMO-PARKER",
        caption="Commonwealth v. Parker",
        year=1984,
        case_type="homicide",
        opinion_text=(
            "OPINION BY THE COURT. Appellant Peter Parker appeals from the order "
            "denying his petition for post-conviction relief. Parker was convicted "
            "of first-degree murder and sentenced to death. In the petition now "
            "before us, Parker contends that his death sentence rested upon "
            "unreliable microscopic hair comparison evidence. At trial, a forensic "
            "examiner testified that hairs recovered at the scene were "
            "microscopically consistent with samples taken from Parker. After "
            "trial, the Federal Bureau of Investigation publicly disclosed that "
            "examiners in its microscopic hair comparison unit had routinely "
            "provided testimony and reports that overstated the significance of "
            "such comparisons beyond the limits of the underlying science. Parker "
            "argues that this disclosure, together with the National Academy of "
            "Sciences' findings on hair microscopy, entitles him to a new trial."
        ),
        real_citation="based on Commonwealth v. Chmiel, 173 A.3d 617 (Pa. 2017); 780 CAP (Pa. 2020)",
    ),
    _DemoCase(
        case_id="DEMO-STARK",
        caption="Commonwealth v. Stark",
        year=1991,
        case_type="sexual_assault",
        opinion_text=(
            "OPINION BY THE COURT. The Commonwealth appeals from an order granting "
            "the motion of Appellee, Anthony Stark, for post-conviction DNA "
            "testing. Stark was convicted of aggravated assault following a trial "
            "at which the Commonwealth relied in part on bite-mark comparison "
            "testimony. A forensic odontologist opined that a wound observed on the "
            "victim was consistent with an impression of Stark's dentition. Stark "
            "contends that bite mark comparison has since been discredited as a "
            "means of identification and that DNA testing of the preserved evidence "
            "could establish a prima facie case for relief. We affirm the order "
            "granting post-conviction testing."
        ),
        real_citation="based on Commonwealth v. Kunco, 173 A.3d 817 (Pa. Super. 2017)",
    ),
    _DemoCase(
        case_id="DEMO-ROGERS",
        caption="State v. Rogers",
        year=1988,
        case_type="homicide",
        opinion_text=(
            "OPINION. Applicant Steven Rogers seeks post-conviction relief from his "
            "conviction for capital murder. Among the State's forensic evidence was "
            "microscopic hair comparison analysis: an analyst testified that a hair "
            "recovered from the scene shared microscopic characteristics with "
            "Rogers's hair. Rogers asserts that microscopic hair comparison has been "
            "recognized as scientifically unreliable for individualization and that "
            "the analyst overstated the probative value of the comparison at trial. "
            "He requests a new hearing at which the limits of the discipline can be "
            "presented to the finder of fact."
        ),
        real_citation="based on Ex parte Hightower, WR-19,518-13 (Tex. Crim. App. 2021)",
    ),
)


class DemoMarvelSource(AcquisitionSource):
    """Offline demo source of de-identified discredited-forensic opinions."""

    jurisdiction = "demo_marvel"
    display_name = "Demo — de-identified public cases (offline)"

    def __init__(self) -> None:
        self._by_id = {c.case_id: c for c in _DEMO_CASES}

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = _DEMO_CASES if limit is None else _DEMO_CASES[:limit]
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
        if row is not None and not case.documents:
            case.documents.append(
                Document(
                    doc_id=f"{case.case_id}-OPINION",
                    case_id=case.case_id,
                    source_uri=f"demo-record://{self.jurisdiction}/{case.case_id}/opinion",
                    media_type="text/plain",
                    needs_ocr=False,
                    normalized_text=row.opinion_text,
                    metadata={"demo_only": True, "real_citation": row.real_citation},
                )
            )
        return case


register_source(DemoMarvelSource())
