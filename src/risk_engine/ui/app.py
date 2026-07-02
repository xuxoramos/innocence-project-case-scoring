"""FastAPI + Jinja2 + htmx UI for intake flagging (replaces the Streamlit POC).

A reviewer fills in an intake form, picks an acquisition source, and submits.
The server structures the intake, runs the Section 5 flow
(``build_packet_for_intake``), and swaps an HTML packet fragment into the page
via htmx. There is no score and no rank anywhere: each verifiable element is
flagged on its own, and missing records are shown as honest gaps (Section 6.6).

Run: ``python -m risk_engine.ui`` (starts uvicorn on http://127.0.0.1:8000).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..acquisition import get_source, list_sources
from ..calibration import calibrated_pipeline
from ..casefiles import CaseFileStore, case_file_from_intake
from ..innocence_project import find_ip_case
from ..intake.structuring import structure_intake
from ..models import SCOPE_STATEMENT
from ..retrieval import build_packet_for_intake
from ..store import CaseStore, THIN_SUPPORT
from .forms import (
    APPLICANT_REF_FIELD,
    CHAPTER_FIELD,
    SOURCE_FIELD,
    case_detail_view,
    case_file_view,
    form_field_groups,
    packet_view,
    parse_intake_form,
)

_HERE = Path(__file__).resolve().parent
_DEFAULT_SOURCE = "allegheny_pa"  # offline-safe fixture; live sources need a token
_CASES_PAGE_SIZE = 100  # browse in pages so the store scales past a few thousand rows

app = FastAPI(title="Intake Flagging POC")
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(_HERE / "templates"))


def _source_options() -> list[dict]:
    options = []
    for key in list_sources():
        try:
            display = get_source(key).display_name or key
        except KeyError:  # pragma: no cover - registry is consistent
            display = key
        options.append({"key": key, "label": display})
    return options


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    sources = _source_options()
    default = _DEFAULT_SOURCE if any(s["key"] == _DEFAULT_SOURCE for s in sources) else None
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "field_groups": form_field_groups(),
            "sources": sources,
            "default_source": default,
        },
    )


@app.post("/flag", response_class=HTMLResponse)
async def flag(request: Request) -> HTMLResponse:
    form = await request.form()
    raw_fields, meta = parse_intake_form({k: str(v) for k, v in form.items()})
    source_key = meta.get(SOURCE_FIELD, _DEFAULT_SOURCE)
    applicant_ref = meta.get(APPLICANT_REF_FIELD, "")
    chapter = meta.get(CHAPTER_FIELD, "PA")

    intake = structure_intake(raw_fields, chapter=chapter, applicant_ref=applicant_ref)
    try:
        # Loads the learned confidence table when present; no-op otherwise.
        packet = build_packet_for_intake(
            intake, source_key=source_key, pipeline=calibrated_pipeline()
        )
    except Exception as exc:  # surface source/network errors in the fragment
        return templates.TemplateResponse(
            request,
            "_error.html",
            {"source_key": source_key, "message": str(exc)},
            status_code=200,
        )

    return templates.TemplateResponse(
        request,
        "_packet.html",
        {"packet": packet_view(packet)},
    )


@app.post("/intake/save", response_class=HTMLResponse)
async def intake_save(request: Request) -> HTMLResponse:
    """Persist a manually-entered intake to the case-file store (spec v3, point 1).

    Structures the submitted form and saves it as a :class:`CaseFile` so it appears
    in the case list. No court records are pulled here — the saved file starts at
    ``record_status=NOT_STARTED`` (an unstarted retrieval, not a clean result, per
    §6.6). The async retrieval that supplements it is a later phase.
    """
    form = await request.form()
    raw_fields, meta = parse_intake_form({k: str(v) for k, v in form.items()})
    applicant_ref = meta.get(APPLICANT_REF_FIELD, "")
    chapter = meta.get(CHAPTER_FIELD, "PA")

    intake = structure_intake(raw_fields, chapter=chapter, applicant_ref=applicant_ref)
    case_file = CaseFileStore.load().add(case_file_from_intake(intake))

    return templates.TemplateResponse(
        request,
        "_saved.html",
        {"case": case_file_view(case_file)},
    )


@app.get("/cases", response_class=HTMLResponse)
def cases(
    request: Request,
    q: str | None = None,
    state: str | None = None,
    factor: str | None = None,
    matched: str | None = None,
    ip: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Browse confirmed exonerations backfilled into the intake schema.

    Read-only and unranked: results come back in stored order with no score or
    sort-by-likelihood. ``matched`` filters gap vs matched cases (Section 6.6),
    ``ip`` filters Innocence Project cases vs other exonerations.
    Results are paged (``_CASES_PAGE_SIZE`` per page) so the store scales.
    """
    store = CaseStore.load()
    matched_filter = {"yes": True, "no": False}.get((matched or "").lower())
    ip_filter = {"yes": True, "no": False}.get((ip or "").lower())
    results = store.filtered(
        query=q or None,
        state=state or None,
        factor=factor or None,
        matched=matched_filter,
        innocence_project=ip_filter,
    )
    submitted = CaseFileStore.load().list()
    match_total = len(results)
    total_pages = max(1, (match_total + _CASES_PAGE_SIZE - 1) // _CASES_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * _CASES_PAGE_SIZE
    page_results = results[start : start + _CASES_PAGE_SIZE]
    filter_query = urlencode(
        {
            k: v
            for k, v in (
                ("q", q),
                ("state", state),
                ("factor", factor),
                ("matched", matched),
                ("ip", ip),
            )
            if v
        }
    )
    return templates.TemplateResponse(
        request,
        "cases.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "results": page_results,
            "submitted": submitted,
            "match_total": match_total,
            "total": len(store),
            "states": store.states(),
            "factors": store.factors(),
            "q": q or "",
            "selected_state": state or "",
            "selected_factor": factor or "",
            "selected_matched": matched or "",
            "selected_ip": ip or "",
            "ip_total": store.innocence_project_count,
            "page": page,
            "total_pages": total_pages,
            "filter_query": filter_query,
            "range_start": start + 1 if page_results else 0,
            "range_end": start + len(page_results),
        },
    )


@app.get("/cases/submitted/{case_id}", response_class=HTMLResponse)
def case_file_detail(request: Request, case_id: str) -> HTMLResponse:
    """Read-only detail view for one submitted intake case file.

    Shows the saved intake rendered as the same §5.1 form the reviewer filled in,
    plus the record-retrieval status. No factors or engine flags yet — those are
    produced once court records are linked (spec v3 points 2–4).
    """
    case_file = CaseFileStore.load().get(case_id)
    back_url = request.headers.get("referer") or "/cases"
    if case_file is None:
        return templates.TemplateResponse(
            request,
            "case_file.html",
            {"scope_statement": SCOPE_STATEMENT, "case": None, "back_url": back_url},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "case_file.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "case": case_file_view(case_file),
            "back_url": back_url,
        },
    )


@app.get("/cases/{nre_id}", response_class=HTMLResponse)
def case_detail(request: Request, nre_id: str) -> HTMLResponse:
    """Read-only detail view for one backfilled exoneration.

    Shows the whole stored record for a single case — jurisdiction, offence, the
    NRE ground-truth factors, and (for matched cases) every engine flag with its
    basis, extraction confidence, verification source, and the source passage it
    was drawn from. Still per-element and unscored (Section 3.1): the page lists
    each flag on its own and never combines them into a case-level number.
    """
    store = CaseStore.load()
    case = store.get(nre_id)
    back_url = request.headers.get("referer") or "/cases"
    if case is None:
        return templates.TemplateResponse(
            request,
            "case_detail.html",
            {"scope_statement": SCOPE_STATEMENT, "case": None, "back_url": back_url},
            status_code=404,
        )
    ip_case = find_ip_case(case) if case.innocence_project else None
    return templates.TemplateResponse(
        request,
        "case_detail.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "case": case_detail_view(case, ip_case),
            "back_url": back_url,
        },
    )


@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request) -> HTMLResponse:
    """Descriptive analytics over the backfilled confirmed exonerations.

    Every chart aggregates one dimension across cases (counts by factor, by
    state) or surfaces the per-element flag-vs-label agreement calibration uses.
    Nothing here combines a single case into a score or rank (Section 3.1).
    """
    store = CaseStore.load()
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "total": len(store),
            "matched_count": store.matched_count,
            "gap_count": store.gap_count,
            "by_category": store.by_category(),
            "by_state": store.by_state(),
            "by_unmapped_factor": store.by_unmapped_factor(),
            "agreement": store.agreement(),
            "thin_support": THIN_SUPPORT,
        },
    )
