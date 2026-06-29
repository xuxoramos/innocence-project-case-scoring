"""Streamlit UI to navigate cases from acquired → OCR/text → tabular.

Lets a reviewer pick a jurisdiction, toggle each (optional) processing step,
pick a scoring algorithm, and walk the ranked worklist. For every case it shows
the source documents, OCR/extraction confidence (separately), and the verbatim
passage behind each flag. No composite "risk score" is ever shown — only a
relative rank — per README sections 5 and 7.

Run: streamlit run src/risk_engine/ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from risk_engine.acquisition import get_source, list_sources  # noqa: E402
from risk_engine.processing import default_pipeline  # noqa: E402
from risk_engine.scoring import get_scorer, list_scorers  # noqa: E402

SCOPE_NOTE = (
    "Flagged on pattern similarity to documented exoneration categories. "
    "This is NOT a determination of innocence; absence of a flag does not "
    "indicate absence of error. Recall-limited (README §3)."
)


def main() -> None:
    st.set_page_config(page_title="Case Triage POC", layout="wide")
    st.title("Systemic Risk Profile Flagging Engine — Triage Worklist")
    st.caption(SCOPE_NOTE)

    jurisdiction = st.sidebar.selectbox("Jurisdiction", list_sources())
    scorer_name = st.sidebar.selectbox("Scoring algorithm", list_scorers())
    st.sidebar.markdown("**Processing steps (each optional)**")
    ocr = st.sidebar.checkbox("OCR", value=True)
    text = st.sidebar.checkbox("Text normalization", value=True)
    tabular = st.sidebar.checkbox("Tabular extraction", value=True)

    source = get_source(jurisdiction)
    pipeline = default_pipeline(ocr=ocr, text=text, tabular=tabular)
    cases = [pipeline.process(source.fetch(c)) for c in source.discover()]
    worklist = get_scorer(scorer_name).rank(cases)

    for entry in worklist.entries:
        c = entry.case
        with st.expander(f"#{entry.rank} — {c.case_id} ({c.year}, {c.case_type})"):
            st.write(f"Documents: {len(c.documents)} · tabular: {c.has_tabular}")
            for doc in c.documents:
                st.text(f"{doc.doc_id} stage={doc.stage.value} ocr_conf={doc.ocr_confidence}")
                if doc.normalized_text:
                    st.code(doc.normalized_text[:500] or "(empty)")
            if c.flags:
                st.subheader("Flags")
                for f in c.flags:
                    st.markdown(
                        f"- **{f.category.value}** ({f.basis.value}) "
                        f"ocr={f.ocr_confidence} extraction={f.extraction_confidence} "
                        f"— passage: `{f.source_passage}`"
                    )
            st.caption(entry.scope_note)


if __name__ == "__main__":  # pragma: no cover
    main()
