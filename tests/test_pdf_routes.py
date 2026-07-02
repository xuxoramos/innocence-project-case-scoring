"""Route tests for the PDF upload / prefill / compare / retain-PDF flow (phase 4)."""

from __future__ import annotations

import pytest

from risk_engine.casefiles import CaseFileStore
from risk_engine.store import CaseStore

_PDF_BYTES = b"%PDF-1.4 minimal fixture bytes for the upload route tests"


class _MemCaseFileStore(CaseFileStore):
    """In-memory stand-in so route tests never touch the real store file."""

    _shared: list = []

    @classmethod
    def load(cls, path=None) -> "_MemCaseFileStore":
        return cls(list(cls._shared))

    def add(self, case_file, path=None):
        _MemCaseFileStore._shared.append(case_file)
        return case_file


def _client(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from risk_engine import casefiles
    from risk_engine.ui import app as app_module

    _MemCaseFileStore._shared = []
    monkeypatch.setattr(app_module.CaseStore, "load", classmethod(lambda cls: CaseStore([])))
    monkeypatch.setattr(app_module, "CaseFileStore", _MemCaseFileStore)
    monkeypatch.setattr(app_module, "start_retrieval", lambda *a, **k: None)
    # Redirect PDF storage to a temp area (helpers resolve the dirs at call time).
    monkeypatch.setattr(casefiles, "DEFAULT_INTAKE_STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(casefiles, "DEFAULT_CASE_PDF_DIR", tmp_path / "stored")
    return TestClient(app_module.app), app_module


def _fake_prefill(text: str):
    from risk_engine.intake.structuring import structure_intake
    from risk_engine.pdf_intake import parse_intake_pairs

    def _inner(path, *, chapter="PA", applicant_ref=""):
        intake = structure_intake(
            parse_intake_pairs(text), chapter=chapter, applicant_ref=applicant_ref
        )
        return intake, text, "embedded"

    return _inner


def test_upload_prefills_and_opens_compare(monkeypatch, tmp_path):
    client, app_module = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app_module,
        "prefill_intake_from_pdf",
        _fake_prefill("Full name: Lee Doe\nOffense: Second-degree murder\n"),
    )
    resp = client.post(
        "/intake/upload",
        files={"pdf": ("intake.pdf", _PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 200
    assert "Confirm intake against the original PDF" in resp.text
    assert 'value="Lee Doe"' in resp.text  # prefilled, editable
    assert "Second-degree murder" in resp.text
    assert 'name="_pdf_token"' in resp.text
    assert "/intake/pdf/" in resp.text  # iframe points at the staged PDF


def test_upload_rejects_non_pdf(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/intake/upload",
        files={"pdf": ("notes.txt", b"just some text", "text/plain")},
    )
    assert resp.status_code == 200
    assert "not a readable PDF" in resp.text


def test_staged_pdf_is_served(monkeypatch, tmp_path):
    client, app_module = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "prefill_intake_from_pdf", _fake_prefill(""))
    upload = client.post(
        "/intake/upload",
        files={"pdf": ("intake.pdf", _PDF_BYTES, "application/pdf")},
    )
    # Find the token in the rendered compare page.
    import re

    match = re.search(r"/intake/pdf/([0-9a-f]+)", upload.text)
    assert match
    served = client.get(f"/intake/pdf/{match.group(1)}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"
    assert served.content == _PDF_BYTES


def test_staged_pdf_missing_is_404(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    assert client.get("/intake/pdf/deadbeef").status_code == 404


def test_save_with_pdf_token_retains_pdf(monkeypatch, tmp_path):
    client, app_module = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app_module, "prefill_intake_from_pdf", _fake_prefill("Full name: Lee Doe\n")
    )
    upload = client.post(
        "/intake/upload",
        files={"pdf": ("original-intake.pdf", _PDF_BYTES, "application/pdf")},
    )
    import re

    token = re.search(r"/intake/pdf/([0-9a-f]+)", upload.text).group(1)

    saved = client.post(
        "/intake/save",
        data={
            "applicant_full_name": "Lee Doe",
            "_chapter": "PA",
            "_pdf_token": token,
            "_pdf_name": "original-intake.pdf",
        },
    )
    assert saved.status_code == 200
    case_file = _MemCaseFileStore._shared[0]
    assert case_file.pdf_stored is True
    assert case_file.pdf_original_name == "original-intake.pdf"

    # The retained PDF is now served from the case-file endpoint...
    served = client.get(f"/cases/submitted/{case_file.case_id}/pdf")
    assert served.status_code == 200
    assert served.content == _PDF_BYTES
    # ...and the detail page embeds it.
    detail = client.get(f"/cases/submitted/{case_file.case_id}")
    assert f"/cases/submitted/{case_file.case_id}/pdf" in detail.text
    assert "Original intake PDF" in detail.text

    # The staged copy was moved out of staging on save.
    assert client.get(f"/intake/pdf/{token}").status_code == 404


def test_save_without_pdf_token_has_no_pdf(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    client.post("/intake/save", data={"applicant_full_name": "No PDF", "_chapter": "PA"})
    case_file = _MemCaseFileStore._shared[0]
    assert case_file.pdf_stored is False
    assert client.get(f"/cases/submitted/{case_file.case_id}/pdf").status_code == 404
