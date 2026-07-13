"""FastAPI + Jinja2 + htmx UI for intake flagging (replaces the Streamlit POC).

A reviewer fills in an intake form, picks an acquisition source, and submits.
The server structures the intake, runs the Section 5 flow
(``build_packet_for_intake``), and swaps an HTML packet fragment into the page
via htmx. There is no score and no rank anywhere: each verifiable element is
flagged on its own, and missing records are shown as honest gaps (Section 6.6).

Run: ``python -m risk_engine.ui`` (starts uvicorn on http://127.0.0.1:8000).
"""

from __future__ import annotations

import base64
import os
import re
import secrets
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..acquisition import get_source, list_sources
from ..calibration import calibrated_pipeline
from ..casefiles import (
    RECORD_STATUS_ACQUIRING,
    RECORD_STATUS_LINKED,
    CaseFileStore,
    case_file_from_intake,
    case_pdf_path,
    looks_like_pdf,
    promote_staged_pdf,
    save_staged_pdf,
    staged_pdf_path,
    update_case_file,
)
from ..casework import start_retrieval
from ..innocence_project import find_ip_case
from ..intake.structuring import structure_intake
from ..models import SCOPE_STATEMENT
from ..pdf_intake import prefill_intake_from_pdf
from ..retrieval import (
    MIN_RECORD_TEXT_CHARS,
    build_packet_for_intake,
    packet_from_pasted_text,
)
from ..store import CaseStore, THIN_SUPPORT
from .forms import (
    APPLICANT_REF_FIELD,
    CHAPTER_FIELD,
    PDF_NAME_FIELD,
    PDF_TOKEN_FIELD,
    SOURCE_FIELD,
    case_detail_view,
    case_file_view,
    form_field_groups,
    intake_datalists,
    packet_view,
    parse_intake_form,
    prefilled_form_groups,
)

_HERE = Path(__file__).resolve().parent
_DEFAULT_SOURCE = "allegheny_pa"  # offline-safe fixture; live sources need a token
_CASES_PAGE_SIZE = 100  # browse in pages so the store scales past a few thousand rows
_MAX_PDF_BYTES = 25 * 1024 * 1024  # reject oversized uploads before reading them into memory

app = FastAPI(title="Intake Flagging POC")
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# Optional HTTP Basic auth. It is enforced only when BOTH credentials are
# supplied via the environment (i.e. in a deployment). Local/dev runs leave
# these unset and stay open, so nothing changes for `python -m risk_engine.ui`.
_AUTH_USER = os.environ.get("RISK_ENGINE_AUTH_USER") or ""
_AUTH_PASSWORD = os.environ.get("RISK_ENGINE_AUTH_PASSWORD") or ""


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    if _AUTH_USER and _AUTH_PASSWORD:
        header = request.headers.get("Authorization", "")
        authorized = False
        if header.startswith("Basic "):
            try:
                user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            except (ValueError, UnicodeDecodeError):
                user = password = ""
            authorized = secrets.compare_digest(user, _AUTH_USER) and secrets.compare_digest(
                password, _AUTH_PASSWORD
            )
        if not authorized:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Intake Flagging POC"'},
            )
    return await call_next(request)


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
            "datalists": intake_datalists(CaseStore.load()),
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
    """Persist a manually-entered intake and kick off record retrieval (spec v3, points 1-2).

    Structures the submitted form, saves it as a :class:`CaseFile` so it appears in
    the case list immediately, then starts an async job that pulls the matching
    public court records in the background. The saved file starts at
    ``record_status=ACQUIRING``; the job drives it to a terminal state (README v2
    §6.6: a linked record, an honest gap, or a retrieval error — never "clean").
    """
    form = await request.form()
    raw_fields, meta = parse_intake_form({k: str(v) for k, v in form.items()})
    source_key = meta.get(SOURCE_FIELD, _DEFAULT_SOURCE)
    applicant_ref = meta.get(APPLICANT_REF_FIELD, "")
    chapter = meta.get(CHAPTER_FIELD, "PA")

    intake = structure_intake(raw_fields, chapter=chapter, applicant_ref=applicant_ref)
    case_file = case_file_from_intake(intake)
    case_file.source_key = source_key
    case_file.record_status = RECORD_STATUS_ACQUIRING
    # If this intake was prefilled from an uploaded PDF, retain that original PDF
    # with the case file so it stays available as the verification surface.
    pdf_token = meta.get(PDF_TOKEN_FIELD, "")
    if pdf_token:
        try:
            if promote_staged_pdf(pdf_token, case_file.case_id):
                case_file.pdf_stored = True
                case_file.pdf_original_name = meta.get(PDF_NAME_FIELD, "") or "intake.pdf"
        except ValueError:  # unsafe token — save without the PDF rather than fail
            pass
    CaseFileStore.load().add(case_file)
    start_retrieval(case_file.case_id, intake, source_key=source_key)

    return templates.TemplateResponse(
        request,
        "_saved.html",
        {"case": case_file_view(case_file)},
    )


@app.post("/intake/upload", response_class=HTMLResponse)
async def intake_upload(request: Request, pdf: UploadFile = File(...)) -> HTMLResponse:
    """Accept an intake PDF, prefill the form, and open the side-by-side compare view.

    The upload is staged (not yet saved), its text extracted offline, and a
    best-effort intake prefill is shown beside the original PDF so the reviewer can
    confirm every field against the source (spec v3 point 1). Nothing is invented:
    unrecognised lines are surfaced separately, blank fields stay blank.
    """
    data = await pdf.read()
    if not data or len(data) > _MAX_PDF_BYTES or not looks_like_pdf(data):
        return templates.TemplateResponse(
            request,
            "_upload_error.html",
            {
                "message": (
                    "That file was not a readable PDF (or was larger than 25 MB). "
                    "Upload the intake as a PDF, or enter it manually."
                )
            },
            status_code=200,
        )

    token = uuid4().hex
    save_staged_pdf(token, data)
    intake, _text, method = prefill_intake_from_pdf(staged_pdf_path(token))

    sources = _source_options()
    default = _DEFAULT_SOURCE if any(s["key"] == _DEFAULT_SOURCE for s in sources) else None
    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "field_groups": prefilled_form_groups(intake),
            "datalists": intake_datalists(CaseStore.load()),
            "sources": sources,
            "default_source": default,
            "pdf_token": token,
            "pdf_name": pdf.filename or "uploaded.pdf",
            "extraction_method": method,
            "unmapped": list(intake.unmapped),
        },
    )


@app.get("/intake/pdf/{token}")
def intake_pdf(token: str) -> FileResponse:
    """Serve a staged (uploaded-but-unsaved) PDF for the compare view's iframe."""
    try:
        path = staged_pdf_path(token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path, media_type="application/pdf", content_disposition_type="inline"
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
            "min_chars": MIN_RECORD_TEXT_CHARS,
        },
    )


@app.get("/cases/submitted/{case_id}/status", response_class=HTMLResponse)
def case_file_status(request: Request, case_id: str) -> HTMLResponse:
    """Live record-retrieval status fragment for one case file (htmx polls this).

    Returns the current ``record_status`` and any linked record searches. While
    retrieval is in flight the fragment carries its own poll trigger; once the
    lifecycle reaches a terminal state (§6.6) the trigger is dropped and polling
    stops. A 404 yields a terminal fragment so a missing id can't poll forever.
    """
    case_file = CaseFileStore.load().get(case_id)
    if case_file is None:
        return templates.TemplateResponse(
            request,
            "_record_status.html",
            {"case": None, "case_id": case_id},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "_record_status.html",
        {"case": case_file_view(case_file)},
    )


@app.get("/cases/submitted/{case_id}/pdf")
def case_file_pdf(case_id: str) -> FileResponse:
    """Serve the original intake PDF retained with a saved case file (spec v3 point 1)."""
    try:
        path = case_pdf_path(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path, media_type="application/pdf", content_disposition_type="inline"
    )


@app.post("/cases/submitted/{case_id}/paste-text", response_class=HTMLResponse)
async def case_file_paste_text(request: Request, case_id: str) -> HTMLResponse:
    """Manual-paste fallback: flag reviewer-pasted record text (spec v3 item 4).

    When live retrieval returned no usable record, the reviewer can paste the
    appellate-brief text. It is flagged by the same pipeline, the case file is
    marked ``LINKED`` with a manual-paste record, and the packet fragment is
    returned inline. Text shorter than the minimum-viable threshold (item 5) is
    rejected rather than flagged on a stub.
    """
    form = await request.form()
    text = str(form.get("text", "")).strip()
    case_file = CaseFileStore.load().get(case_id)
    if case_file is None:
        raise HTTPException(status_code=404, detail="not found")
    if len(text) < MIN_RECORD_TEXT_CHARS:
        return templates.TemplateResponse(
            request,
            "_paste_error.html",
            {"min_chars": MIN_RECORD_TEXT_CHARS, "got": len(text), "case_id": case_id},
        )
    intake = case_file.to_intake()
    packet = packet_from_pasted_text(
        intake, text, case_id=case_id, pipeline=calibrated_pipeline()
    )
    searches = [
        {"record_type": r.record_type, "status": r.status.value, "detail": r.detail}
        for r in packet.records
    ]
    update_case_file(
        case_id,
        record_status=RECORD_STATUS_LINKED,
        source_key="manual_paste",
        record_searches=searches,
        retrieval_error="",
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return templates.TemplateResponse(request, "_packet.html", {"packet": packet_view(packet)})


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


#: Human descriptions for each registered record source, keyed by jurisdiction.
#: Kept here (not in the source classes) so the class layer stays free of UI copy.
_SOURCE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "allegheny_pa": {
        "kind": "Offline fixture",
        "scope": "Placeholder Allegheny County (Pittsburgh) stubs — a pilot seam, not real "
        "opinions yet.",
    },
    "demo_marvel": {
        "kind": "Offline fixture",
        "scope": "De-identified real public opinions used only for demos. Never training or "
        "label data.",
    },
    "appellate_cl": {
        "kind": "Live API (CourtListener)",
        "scope": "U.S. appellate opinions, nationwide, fetched on demand from the CourtListener "
        "REST API.",
    },
    "pa_appellate_cl": {
        "kind": "Live API (CourtListener)",
        "scope": "Pennsylvania appellate opinions (PA Supreme Court + Superior Court), fetched on "
        "demand from CourtListener.",
    },
}


#: The authoritative scientific sources behind the discredited-method flags, with
#: acronyms expanded and a link where a stable public one exists. Ordered longest
#: token first so the linkifier never matches a short token inside a longer one.
#: ``token`` is the exact phrasing used in ``forensic.py`` authority strings.
_AUTHORITY_LINKS: tuple[tuple[str, str, str], ...] = (
    (
        "Texas Forensic Science Commission moratorium recommendation (2016)",
        "Texas Forensic Science Commission moratorium recommendation (2016)",
        "https://www.txcourts.gov/fsc/",
    ),
    (
        "FBI/DOJ microscopic-hair review (2015)",
        "Federal Bureau of Investigation / Department of Justice (FBI/DOJ) "
        "microscopic-hair review (2015)",
        "https://www.fbi.gov/news/press-releases/fbi-testimony-on-microscopic-hair-analysis-"
        "contained-errors-in-at-least-90-percent-of-cases-in-ongoing-review",
    ),
    (
        "FBI abandonment of the technique (2005)",
        "Federal Bureau of Investigation (FBI) abandonment of the technique (2005)",
        "",
    ),
    (
        "NFPA 921 fire-investigation standard",
        "National Fire Protection Association (NFPA) 921 fire-investigation standard",
        "https://www.nfpa.org/codes-and-standards/nfpa-921-standard-development/921",
    ),
    (
        "PCAST 2016",
        "President's Council of Advisors on Science and Technology (PCAST) 2016",
        "https://obamawhitehouse.archives.gov/sites/default/files/microsites/ostp/PCAST/"
        "pcast_forensic_science_report_final.pdf",
    ),
    (
        "NAS 2009",
        "National Academy of Sciences (NAS) 2009",
        "https://www.nationalacademies.org/publications/12589",
    ),
    (
        "NAS 2004",
        "National Academy of Sciences (NAS) 2004",
        "https://www.nationalacademies.org/publications/10924",
    ),
    (
        "Innocence Project casework",
        "Innocence Project casework",
        "https://innocenceproject.org/misapplication-of-forensic-science/",
    ),
)

#: Bibliography rows for the data-sources page (expanded names + links).
_SCIENCE_SOURCES: tuple[dict[str, str], ...] = tuple(
    {"label": label, "url": url} for _tok, label, url in _AUTHORITY_LINKS if url
)

_AUTHORITY_RE = re.compile(
    "|".join(re.escape(tok) for tok, _label, _url in _AUTHORITY_LINKS)
)
_AUTHORITY_BY_TOKEN = {tok: (label, url) for tok, label, url in _AUTHORITY_LINKS}


def _linkify_authority(text: str) -> str:
    """Expand acronyms and hyperlink known citing authorities in ``text``.

    Returns HTML with each recognized authority replaced by its expanded name,
    linked when a stable public source exists. Input is our own curated data
    (``forensic.py``), never user input, so the emitted anchors are safe.
    """
    escaped = html_escape(text)

    def _replace(match: "re.Match[str]") -> str:
        label, url = _AUTHORITY_BY_TOKEN[match.group(0)]
        label = html_escape(label)
        if url:
            return f'<a href="{html_escape(url)}" target="_blank" rel="noopener">{label}</a>'
        return label

    # Match against the escaped text; the tokens contain no HTML-special chars,
    # so escaping does not alter them.
    return _AUTHORITY_RE.sub(_replace, escaped)


@app.get("/data-sources", response_class=HTMLResponse)
def data_sources(request: Request) -> HTMLResponse:
    """Describe the universe of records the engine can draw on (record sources).

    Enumerates the registered acquisition sources with their kind and scope, and
    reports the size of the offline fixtures and the exoneration reference corpus.
    Purely descriptive — no case is scored or ranked here (Section 3.1).
    """
    from ..forensic import FORENSIC_METHOD_REFERENCE, TIER_MEANING

    rows = []
    for key in list_sources():
        try:
            source = get_source(key)
        except KeyError:  # pragma: no cover - registry is consistent
            continue
        meta = _SOURCE_DESCRIPTIONS.get(key, {"kind": "Record source", "scope": ""})
        # Only count offline fixtures; live sources are on-demand and need network.
        if meta["kind"].startswith("Offline"):
            try:
                count = str(len(list(source.discover())))
            except Exception:  # pragma: no cover - offline fixtures don't raise
                count = "—"
        else:
            count = "On demand"
        rows.append(
            {
                "key": key,
                "label": source.display_name or key,
                "kind": meta["kind"],
                "scope": meta["scope"],
                "records": count,
            }
        )

    # The debunked-science data source: the discredited/limited forensic-method
    # reference each DISCREDITED_FORENSIC_METHOD flag is checked against. Sorted by
    # tier (A formally invalidated, then B, then C) so the strongest sit on top.
    forensic_methods = sorted(
        (
            {
                "method": ref.method,
                "status": ref.status,
                "tier": ref.tier,
                "tier_meaning": TIER_MEANING.get(ref.tier, ""),
                "authority": ref.authority,
                "authority_html": _linkify_authority(ref.authority),
                "source": ref.source,
            }
            for ref in FORENSIC_METHOD_REFERENCE
        ),
        key=lambda m: (m["tier"], m["method"]),
    )

    store = CaseStore.load()
    return templates.TemplateResponse(
        request,
        "data_sources.html",
        {
            "scope_statement": SCOPE_STATEMENT,
            "sources": rows,
            "exoneration_count": len(store),
            "forensic_method_count": len(FORENSIC_METHOD_REFERENCE),
            "forensic_methods": forensic_methods,
            "science_sources": _SCIENCE_SOURCES,
        },
    )
