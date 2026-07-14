# Demo Script — Intake Flagging POC (with a lawyer)

A live, click-through demo of what the tool does at intake and, just as
importantly, what it refuses to do. Runs entirely against the deployed instance
using three **real, famous exonerations** and their **real, public-domain court
records** (verbatim appellate opinions pulled from CourtListener). These are
confirmed, public exonerations, so the tool uses the real names; the flagged
forensic content is exactly what the real record says. The demo data is
walled off from anything that trains or calibrates the system.

## 0. Before you start

- Open http://178.105.112.86:8000 and log in as user `reviewer`.
- Get the current password (never printed to chat/screen):

  ```bash
  ssh hetzner-web 'grep PASSWORD /etc/innocence-app.env'
  ```

- Opening line to say: "This tool doesn't decide who's innocent, and it never
  scores or ranks a case. At intake it flags whether the case record contains
  elements matching documented categories of concern, each one checkable against
  an outside source. Watch what it does, and what it deliberately won't do."

Two buttons matter on the intake form:
- **Flag elements** runs the analysis and shows a packet. It persists **nothing**.
  Use this for the walkthrough and you have nothing to clean up.
- **Save to worklist** persists the intake to the worklist and kicks off
  background record retrieval. Only use it if you want to show the worklist and
  the record/docket lifecycle; the clean-up section below removes exactly those
  saved demo rows.

For every case below, set **Record source** to
**"Demo — famous exonerations (real records, offline)"**.

> **Note on the form fields.** The tool locates a record by the applicant
> **name** and **year of conviction** only (there is no geographic gate), so the
> offense and county boxes are for your notes and won't change what is found.
> Type the values in; they need not appear in the autocomplete list.

---

## 1. Case one — Keith Harward (the headline: bite-mark)

Keith Harward was convicted of a 1982 Newport News murder partly on **bite-mark
comparison** testimony and exonerated by DNA in 2016 after 33 years. The record
below is his real 1988 Court of Appeals of Virginia opinion.

Fill the form:

| Field | Value |
|---|---|
| Applicant full name | `Keith Harward` |
| Offense(s) convicted of | `First-degree murder` |
| Conviction county / city / state | `Newport News, VA` |
| Court type (state / federal) | `state` |
| Date of conviction | `1986` |
| Sentence received | `Life` |
| Record source | Demo — famous exonerations (real records, offline) |

Click **Flag elements**. Point at three things:
1. The single **Discredited forensic method** flag — bite-mark identification.
2. The **verification source** beside it (the forensic-odontology discreditation).
   Say: "This is *why* it's flagged, and it has nothing to do with guilt. It's a
   finding about the method, checkable on its own."
3. The **source passage** quoted from the real opinion — and that there is **no
   score, no rank, no 'likelihood of innocence' anywhere on the page.**

To show the record lifecycle (optional), click **Save to worklist** instead and
open the case from the worklist: the tool retrieved **both the appellate opinion
and the trial-court docket**, and it reports **post-conviction filings** as a
gap — a record it did not retrieve, not a clean bill.

---

## 2. Case two — John Norman Huffington (hair + a second flag)

Huffington was convicted of a 1981 Maryland double murder on **microscopic hair
comparison** testimony from the discredited FBI hair unit (analyst Michael
Malone); his convictions were vacated and he was exonerated. The record is his
real 1998 Fourth Circuit opinion.

| Field | Value |
|---|---|
| Applicant full name | `John Norman Huffington` |
| Offense(s) convicted of | `First-degree murder` |
| Conviction county / city / state | `Harford County, MD` |
| Court type (state / federal) | `state` |
| Date of conviction | `1981` |
| Sentence received | `Death` |
| Record source | Demo — famous exonerations (real records, offline) |

Click **Flag elements**. Result: **two flags on one real case** — a
**Discredited forensic method** flag (microscopic hair analysis) *and* a
**Prosecutor misconduct** flag drawn from the same opinion. Point out that each
stands on its own passage and source, and the two are listed separately, never
combined into a single number.

---

## 3. Case three — David Chmiel (same method, a Pennsylvania case)

Chmiel is a Pennsylvania capital case (No. 780 CAP, Lackawanna County) in which
the Pennsylvania Supreme Court addressed **microscopic hair comparison** in
light of the FBI review. The record is that real 2020 opinion.

| Field | Value |
|---|---|
| Applicant full name | `David Chmiel` |
| Offense(s) convicted of | `First-degree murder` |
| Conviction county / city / state | `Lackawanna County, PA` |
| Court type (state / federal) | `state` |
| Date of conviction | `1983` |
| Sentence received | `Death` |
| Record source | Demo — famous exonerations (real records, offline) |

Click **Flag elements**. Result: another **microscopic hair comparison**
discredited-forensic flag (plus a witness-identification circumstance).
Talking point: the tool doesn't gate on jurisdiction — the same method is
checkable whether the case was tried in Virginia, Maryland, or Pennsylvania.

---

## 4. The most important 30 seconds — a gap is not a clean bill

Run one more intake with a name the source does **not** contain:

| Field | Value |
|---|---|
| Applicant full name | `Bruce Banner` |
| Offense(s) convicted of | `First-degree murder` |
| Date of conviction | `1990` |
| Record source | Demo — famous exonerations (real records, offline) |

Click **Flag elements**. The result reports **records searched, nothing matched —
a gap**, not a clean result. Say: "This is the line the tool is
careful about. A gap in the record is reported as a gap. It never tells you the
case is fine just because it found nothing. Absence of a flag is not absence of a
problem."

---

## 5. Talking points to keep handy

- Every flag is **element-level and checkable** against a source independent of
  guilt or innocence.
- There is **no case-level score and no ranking**, by design — so the tool can't
  be used to sort people into "more" or "less" innocent.
- These three are **real, confirmed exonerations**, and the records are their
  **real, public-domain court opinions**. It is demo-only data, walled off from
  anything that trains or calibrates the system.

---

## 6. Clean-up (run between or after demos)

**If you only used "Flag elements", there is nothing to clean up** — that path
persists nothing.

If you (or the lawyer) clicked **Save to worklist** on any demo case, remove
exactly those saved demo rows with the command below. It is targeted: it only
drops case files whose `source_key` is `demo_famous` from the SQLite store
(`app.db`) and refreshes the reviewable JSONL export. It never touches real
submitted intakes or the exoneration store.

```bash
for i in $(seq 1 8); do ssh -o ConnectTimeout=15 hetzner-web 'runuser -u innocence -- python3 - <<PY
import json, os, sqlite3
from pathlib import Path
base = Path("/opt/innocence-project-case-scoring/data/processed")
dbf = base / "app.db"
pdfs = base / "case_pdfs"
if not dbf.exists():
    print("no app.db; nothing to clean"); raise SystemExit
conn = sqlite3.connect(str(dbf))
conn.row_factory = sqlite3.Row
ids = [r[0] for r in conn.execute("SELECT case_id FROM case_files WHERE source_key = ?", ("demo_famous",))]
conn.execute("DELETE FROM case_files WHERE source_key = ?", ("demo_famous",))
conn.commit()
rows = conn.execute("SELECT * FROM case_files ORDER BY submitted_at").fetchall()
def rec(r):
    return {"case_id": r["case_id"], "provenance": r["provenance"], "submitted_at": r["submitted_at"], "chapter": r["chapter"], "applicant_ref": r["applicant_ref"], "fields": json.loads(r["fields"]), "unmapped": json.loads(r["unmapped"]), "record_status": r["record_status"], "source_key": r["source_key"], "record_searches": json.loads(r["record_searches"]), "retrieval_error": r["retrieval_error"], "retrieved_at": r["retrieved_at"], "pdf_stored": bool(r["pdf_stored"]), "pdf_original_name": r["pdf_original_name"]}
export = base / "case_files.jsonl"
tmp = export.with_suffix(".jsonl.tmp")
tmp.write_text("".join(json.dumps(rec(r), sort_keys=True) + chr(10) for r in rows))
os.replace(tmp, export)
conn.close()
removed = 0
for cid in ids:
    p = pdfs / (str(cid) + ".pdf")
    if p.exists():
        p.unlink(); removed += 1
print("removed", len(ids), "demo case file(s) from DB;", removed, "pdf(s); kept", len(rows))
PY
' 2>&1 && break; echo "clean-up retry $i"; sleep 3; done
```

The case list refreshes on next load, so no restart is needed. To confirm it's
clean, reload `/cases` in the browser and check no demo applicants remain.

---

*Demo data lives in `src/risk_engine/acquisition/demo_famous.py` (source key
`demo_famous`) and the verbatim opinions under `data/demo/famous/`. It is
demonstration-only and must never be used as training or label data.*
