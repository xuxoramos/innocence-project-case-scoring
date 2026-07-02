"""Tests for the exoneration case store (persistence, query, analytics)."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from risk_engine.acquisition import register_source
from risk_engine.acquisition.base import AcquisitionSource
from risk_engine.labels import ExonerationRecord
from risk_engine.models import Case, Document, FlagCategory
from risk_engine.store import (
    CaseStore,
    StoredCase,
    StoredFlag,
    backfill_cases,
    backfill_store,
    load_cases,
    save_cases,
    stored_from_example,
)

_FORENSIC = FlagCategory.DISCREDITED_FORENSIC_METHOD.value


class _StoreSource(AcquisitionSource):
    """In-memory source with one named, flag-bearing opinion (offline)."""

    jurisdiction = "store_test_src"
    display_name = "Store Test Source"

    _DATA = [
        (
            "Commonwealth v. Doswell",
            1986,
            "The conviction rested on bite-mark comparison evidence at trial.",
        ),
    ]

    def discover(self, limit: int | None = None) -> Iterable[Case]:
        rows = self._DATA if limit is None else self._DATA[:limit]
        for i, (caption, year, text) in enumerate(rows):
            case = Case(case_id=f"S-{i}", jurisdiction=self.jurisdiction, year=year)
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


register_source(_StoreSource())


def _record(**overrides) -> ExonerationRecord:
    return ExonerationRecord(
        nre_id=overrides.get("nre_id", "NRE-1"),
        name=overrides.get("name", "Thomas Doswell"),
        state=overrides.get("state", "Pennsylvania"),
        county=overrides.get("county", "Allegheny"),
        crime=overrides.get("crime", "Sexual Assault"),
        crime_year=overrides.get("crime_year", 1986),
        conviction_year=overrides.get("conviction_year", 1986),
        factors=overrides.get(
            "factors",
            {"False or Misleading Forensic Evidence", "Official Misconduct"},
        ),
    )


def _stored(**kw) -> StoredCase:
    base = dict(
        provenance="nre_exoneration",
        nre_id="X",
        name="Pat Doe",
        state="Pennsylvania",
        county="Allegheny",
        crime="Robbery",
        crime_year=1990,
        conviction_year=1991,
        matched=True,
        labels=[],
        unmapped_factors=[],
        predicted=[],
        flags=[],
    )
    base.update(kw)
    return StoredCase(**base)


# --- conversion (both branches, offline) ------------------------------------


def test_backfill_matched_records_flags_and_predictions():
    [case] = backfill_cases([_record()], match=True, source_key="store_test_src")
    assert case.matched is True
    assert case.name == "Thomas Doswell"
    assert _FORENSIC in case.labels  # NRE ground truth
    assert _FORENSIC in case.predicted  # engine independently fired it
    assert any(f.category == _FORENSIC for f in case.flags)
    # "Official Misconduct" is an unmapped NRE rollup, recorded but not a category.
    assert "Official Misconduct" in case.unmapped_factors


def test_backfill_attaches_case_seriousness_descriptor():
    # _record()'s crime is "Sexual Assault" -> serious violent felony; the grade
    # rides along on each element flag as a labelled descriptor, never summed.
    [case] = backfill_cases([_record()], match=True, source_key="store_test_src")
    assert case.flags
    for flag in case.flags:
        assert flag.descriptors["case_seriousness"] == "serious violent felony"
        assert flag.descriptors["seriousness_basis"]


def test_backfill_offline_is_a_gap_with_labels_but_no_predictions():
    [case] = backfill_cases([_record()], match=False)
    assert case.matched is False  # no court record looked up
    assert case.predicted == []  # gap, not a clean result (Section 6.6)
    assert case.flags == []
    assert _FORENSIC in case.labels  # labels still back-filled offline


def test_stored_from_example_gap_has_no_predictions():
    from risk_engine.dataset import LabeledExample, intake_from_exoneration

    rec = _record()
    example = LabeledExample(
        exoneration=rec,
        intake=intake_from_exoneration(rec),
        match=None,
        labels=rec.categories(),
    )
    case = stored_from_example(example)
    assert case.matched is False
    assert case.predicted == []
    assert case.jurisdiction == "Allegheny County, Pennsylvania"


# --- persistence ------------------------------------------------------------


def test_save_load_roundtrip(tmp_path):
    cases = [
        _stored(nre_id="A", labels=[_FORENSIC], predicted=[_FORENSIC],
                flags=[StoredFlag(_FORENSIC, "directly_stated", 0.9, "bite mark", None)]),
        _stored(nre_id="B", matched=False, labels=[_FORENSIC]),
    ]
    path = save_cases(cases, tmp_path / "store.jsonl")
    loaded = load_cases(path)
    assert [c.nre_id for c in loaded] == ["A", "B"]
    assert loaded[0].flags[0].source_passage == "bite mark"
    assert loaded[1].matched is False


def test_load_missing_returns_empty(tmp_path):
    assert load_cases(tmp_path / "absent.jsonl") == []


# --- resumable backfill + progress ------------------------------------------


def test_backfill_store_persists_each_record_and_logs_progress(tmp_path):
    path = tmp_path / "store.jsonl"
    events: list[tuple[int, int, str]] = []
    cases = backfill_store(
        [_record()],
        path=path,
        match=True,
        source_key="store_test_src",
        progress=lambda done, total, status, case: events.append((done, total, status)),
    )
    assert [c.matched for c in cases] == [True]
    assert load_cases(path)[0].matched is True  # persisted to disk
    assert events == [(1, 1, "matched")]


def test_backfill_store_resume_skips_already_linked(tmp_path):
    path = tmp_path / "store.jsonl"
    backfill_store([_record()], path=path, source_key="store_test_src", progress=None)
    statuses: list[str] = []
    backfill_store(
        [_record()],
        path=path,
        source_key="store_test_src",
        progress=lambda d, t, status, c: statuses.append(status),
    )
    assert statuses == ["cached"]  # already matched -> not reprocessed


def test_backfill_store_matched_run_upgrades_a_prior_gap(tmp_path):
    path = tmp_path / "store.jsonl"
    backfill_store([_record()], path=path, match=False, progress=None)  # offline gap
    assert load_cases(path)[0].matched is False
    statuses: list[str] = []
    backfill_store(
        [_record()],
        path=path,
        match=True,
        source_key="store_test_src",
        progress=lambda d, t, status, c: statuses.append(status),
    )
    assert statuses == ["matched"]  # the gap was reprocessed, not skipped
    assert load_cases(path)[0].matched is True


def test_backfill_store_no_resume_reprocesses(tmp_path):
    path = tmp_path / "store.jsonl"
    backfill_store([_record()], path=path, source_key="store_test_src", progress=None)
    statuses: list[str] = []
    backfill_store(
        [_record()],
        path=path,
        source_key="store_test_src",
        resume=False,
        progress=lambda d, t, status, c: statuses.append(status),
    )
    assert statuses == ["matched"]  # resume disabled -> redo everything


# --- query ------------------------------------------------------------------


def _store() -> CaseStore:
    return CaseStore(
        [
            _stored(nre_id="1", name="Thomas Doswell", state="Pennsylvania",
                    labels=[_FORENSIC], predicted=[_FORENSIC]),
            _stored(nre_id="2", name="Jane Roe", state="New York",
                    labels=[FlagCategory.PROSECUTOR_MISCONDUCT.value]),
            _stored(nre_id="3", name="John Poe", state="Pennsylvania",
                    matched=False, labels=[_FORENSIC]),
        ]
    )


def test_filter_by_name_state_factor_and_matched():
    store = _store()
    assert [c.nre_id for c in store.filtered(query="doe")] == []
    assert [c.nre_id for c in store.filtered(query="doswell")] == ["1"]
    assert {c.nre_id for c in store.filtered(state="pennsylvania")} == {"1", "3"}
    assert {c.nre_id for c in store.filtered(factor=_FORENSIC)} == {"1", "3"}
    assert [c.nre_id for c in store.filtered(matched=False)] == ["3"]
    # combined
    assert [c.nre_id for c in store.filtered(state="Pennsylvania", matched=True)] == ["1"]


def test_counts_and_dimensions():
    store = _store()
    assert store.matched_count == 2
    assert store.gap_count == 1
    assert store.states() == ["New York", "Pennsylvania"]
    assert _FORENSIC in store.factors()
    assert dict(store.by_state())["Pennsylvania"] == 2
    assert dict(store.by_category())[_FORENSIC] == 2


# --- analytics: agreement (matched only, gaps excluded) ---------------------


def test_agreement_excludes_gaps_and_marks_thin_support():
    store = CaseStore(
        [
            _stored(matched=True, labels=[_FORENSIC], predicted=[_FORENSIC]),  # TP
            _stored(matched=True, labels=[], predicted=[_FORENSIC]),           # FP
            _stored(matched=True, labels=[_FORENSIC], predicted=[]),           # FN
            _stored(matched=False, labels=[_FORENSIC], predicted=[]),          # gap: excluded
        ]
    )
    [agreement] = [a for a in store.agreement() if a.category == _FORENSIC]
    assert agreement.true_positive == 1
    assert agreement.false_positive == 1
    assert agreement.false_negative == 1  # the gap is NOT counted here
    assert agreement.fired == 2
    assert agreement.support == 2
    assert agreement.precision == pytest.approx(0.5)
    assert agreement.recall == pytest.approx(0.5)
    assert agreement.thin is True


def test_confidence_table_is_precision_per_fired_category():
    store = CaseStore(
        [
            _stored(matched=True, labels=[_FORENSIC], predicted=[_FORENSIC]),  # TP
            _stored(matched=True, labels=[], predicted=[_FORENSIC]),           # FP
            _stored(matched=False, labels=[_FORENSIC], predicted=[]),          # gap: excluded
        ]
    )
    table = store.confidence_table()
    assert table[_FORENSIC] == pytest.approx(0.5)  # 1 TP / (1 TP + 1 FP)


def test_run_calibrate_from_store_derives_table_without_network(tmp_path):
    from risk_engine.calibration import load_calibration
    from risk_engine.cli import run_calibrate

    store_path = tmp_path / "store.jsonl"
    save_cases(
        [
            _stored(nre_id="1", matched=True, labels=[_FORENSIC], predicted=[_FORENSIC]),
            _stored(nre_id="2", matched=True, labels=[], predicted=[_FORENSIC]),
        ],
        store_path,
    )
    out = tmp_path / "cal.json"
    report = run_calibrate(
        source_key="store_test_src",
        state=None,
        county=None,
        max_records=None,
        match_limit=50,
        out=str(out),
        save=True,
        from_store=True,
        store_path=str(store_path),
    )
    table = load_calibration(out)
    assert table[FlagCategory.DISCREDITED_FORENSIC_METHOD] == pytest.approx(0.5)
    assert "matched case" in report


# --- UI routes --------------------------------------------------------------


def test_cases_and_analytics_routes(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: _store()))
    client = TestClient(app_module.app)

    cases = client.get("/cases")
    assert cases.status_code == 200
    assert "Thomas Doswell" in cases.text
    assert "confirmed exonerations" in cases.text.lower()

    filtered = client.get("/cases", params={"matched": "no"})
    assert "John Poe" in filtered.text
    assert "Thomas Doswell" not in filtered.text

    analytics = client.get("/analytics")
    assert analytics.status_code == 200
    assert "matched cases only" in analytics.text.lower()


def test_cases_route_empty_state(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: CaseStore([])))
    client = TestClient(app_module.app)
    resp = client.get("/cases")
    assert resp.status_code == 200
    assert "No backfilled cases yet" in resp.text


def test_cases_route_innocence_project_badge_and_filter(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    store = CaseStore(
        [
            _stored(nre_id="1", name="Marvin Anderson", state="Virginia", innocence_project=True),
            _stored(nre_id="2", name="Other Person", state="Texas", innocence_project=False),
        ]
    )
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: store))
    client = TestClient(app_module.app)

    allcases = client.get("/cases")
    assert allcases.status_code == 200
    assert 'class="badge ip"' in allcases.text  # badge rendered for the IP case
    assert "Marvin Anderson" in allcases.text and "Other Person" in allcases.text

    ip_only = client.get("/cases", params={"ip": "yes"})
    assert "Marvin Anderson" in ip_only.text
    assert "Other Person" not in ip_only.text

    other = client.get("/cases", params={"ip": "no"})
    assert "Other Person" in other.text
    assert "Marvin Anderson" not in other.text


def test_cases_route_paginates(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    page_size = app_module._CASES_PAGE_SIZE
    big = CaseStore([_stored(nre_id=str(i), name=f"Case {i}") for i in range(page_size + 25)])
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: big))
    client = TestClient(app_module.app)

    page1 = client.get("/cases")
    assert page1.status_code == 200
    assert page1.text.lower().count("</tr>") - 1 == page_size  # one page, minus header row
    assert "Page 1 of 2" in page1.text
    assert "page=2" in page1.text  # next link present

    page2 = client.get("/cases", params={"page": 2})
    assert page2.text.lower().count("</tr>") - 1 == 25  # remainder
    assert "Page 2 of 2" in page2.text

    # out-of-range page clamps to the last page instead of erroring
    clamped = client.get("/cases", params={"page": 999})
    assert clamped.status_code == 200
    assert "Page 2 of 2" in clamped.text


def test_store_get_returns_case_or_none():
    store = _store()
    assert store.get("2").name == "Jane Roe"
    assert store.get("missing") is None


def test_case_detail_route_shows_flags_and_factors(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    store = CaseStore(
        [
            _stored(
                nre_id="1",
                name="Thomas Doswell",
                labels=[_FORENSIC],
                unmapped_factors=["Official Misconduct"],
                predicted=[_FORENSIC],
                flags=[StoredFlag(_FORENSIC, "directly_stated", 0.91, "bite mark comparison", None)],
            )
        ]
    )
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: store))
    client = TestClient(app_module.app)

    resp = client.get("/cases/1")
    assert resp.status_code == 200
    assert "Thomas Doswell" in resp.text
    assert "bite mark comparison" in resp.text  # source passage surfaced
    assert "Official Misconduct" in resp.text  # blind-spot factor shown
    assert "0.91" in resp.text  # extraction confidence rendered
    # enriched: human factor label + description, checkable/blind-spot pills
    assert "Discredited forensic method" in resp.text
    assert "checkable" in resp.text
    assert "blind spot" in resp.text
    # the data behind each tag: NRE source field for checkable, reason for blind spot
    assert "False or Misleading Forensic Evidence" in resp.text  # why it is checkable
    assert "avoid counting the same conduct twice" in resp.text  # why it is a blind spot

    # the browse row links to the detail page
    listing = client.get("/cases")
    assert 'href="/cases/1"' in listing.text


def test_case_detail_route_renders_intake_form(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    store = CaseStore(
        [_stored(nre_id="1", name="Thomas Doswell", crime="Rape", conviction_year=1986)]
    )
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: store))
    client = TestClient(app_module.app)

    resp = client.get("/cases/1")
    assert resp.status_code == 200
    # the stored exoneration is rendered as a filled intake form
    assert "Innocence Project intake form" in resp.text
    assert "Applicant full name" in resp.text
    assert "Offense(s) convicted of" in resp.text
    assert "Claims actual innocence" in resp.text
    # narrative fields the NRE cannot supply are shown as gaps, never invented
    assert "not provided" in resp.text



def test_case_detail_route_links_innocence_project(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.innocence_project import IPCase
    from risk_engine.ui import app as app_module

    store = CaseStore([_stored(nre_id="7", name="Alan Crotzer", state="Florida", innocence_project=True)])
    roster = [IPCase(name="Alan Crotzer", slug="alan-crotzer", state="Florida", exoneration_year="2006")]
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: store))
    monkeypatch.setattr(app_module, "find_ip_case", lambda case: roster[0])
    client = TestClient(app_module.app)

    resp = client.get("/cases/7")
    assert resp.status_code == 200
    assert "innocenceproject.org/cases/alan-crotzer/" in resp.text  # links to IP page
    assert "2006" in resp.text  # exoneration year surfaced



def test_case_detail_route_gap_and_missing(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    store = CaseStore([_stored(nre_id="9", name="Gap Person", matched=False, predicted=[], flags=[])])
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: store))
    client = TestClient(app_module.app)

    gap = client.get("/cases/9")
    assert gap.status_code == 200
    assert "retrieval gap" in gap.text.lower()

    missing = client.get("/cases/nope")
    assert missing.status_code == 404
    assert "not found" in missing.text.lower()


def test_intake_datalists_distinct_registry_values():
    from risk_engine.ui.forms import intake_datalists

    store = CaseStore(
        [
            _stored(nre_id="1", crime="Robbery", state="Pennsylvania", county="Allegheny"),
            _stored(nre_id="2", crime="Murder", state="Texas", county="Harris"),
            _stored(nre_id="3", crime="Robbery", state="Texas", county="Harris"),
        ]
    )
    lists = intake_datalists(store)
    # distinct offenses, sorted, deduped
    assert lists["offense_convicted_of"] == ["Murder", "Robbery"]
    # distinct jurisdictions ("County County, State"), sorted, deduped
    assert lists["conviction_jurisdiction"] == [
        "Allegheny County, Pennsylvania",
        "Harris County, Texas",
    ]


def test_index_route_renders_autocomplete_datalists(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine.ui import app as app_module

    store = CaseStore([_stored(nre_id="1", crime="Arson", state="Ohio", county="Cuyahoga")])
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: store))
    client = TestClient(app_module.app)

    resp = client.get("/")
    assert resp.status_code == 200
    # the offense field is wired to a datalist seeded from the registry
    assert 'list="dl-offense_convicted_of"' in resp.text
    assert '<datalist id="dl-offense_convicted_of">' in resp.text
    assert '<option value="Arson">' in resp.text
    # the jurisdiction field too
    assert 'list="dl-conviction_jurisdiction"' in resp.text
    assert '<option value="Cuyahoga County, Ohio">' in resp.text


