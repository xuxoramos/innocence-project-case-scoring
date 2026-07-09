# Demo Script — Intake Flagging POC (with a lawyer)

A live, click-through demo of what the tool does at intake and, just as
importantly, what it refuses to do. Runs entirely against the deployed instance
using three **real, de-identified public cases** (Marvel civilian aliases). No
real person's identity ever enters the pipeline; only the forensic content does.

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
- **Save** persists the intake to the case list and kicks off background record
  retrieval. Only use it if you want to show the case list; the clean-up section
  below removes exactly those saved demo rows.

For every case below, set **Record source** to
**"Demo — de-identified public cases (offline)"**.

---

## 1. Case one — "Peter Parker" (the headline)

Behind the alias (operator eyes only, do not say on camera): a Pennsylvania
capital case built partly on microscopic hair comparison.

Fill the form:

| Field | Value |
|---|---|
| Applicant full name | `Peter Parker` |
| Offense(s) convicted of | `First-degree murder` |
| Conviction county / city / state | `Lackawanna County, PA` |
| Court type (state / federal) | `state` |
| Date of conviction | `1984` |
| Sentence received | `Death` |
| Record source | Demo — de-identified public cases (offline) |

Click **Flag elements**. Point at three things:
1. The single **Discredited forensic method** flag — microscopic hair comparison.
2. The **verification source** beside it (NAS 2009 / FBI-DOJ hair review). Say:
   "This is *why* it's flagged, and it has nothing to do with guilt. It's a
   finding about the method, checkable on its own."
3. The **source passage** quoted from the record — and that there is **no score,
   no rank, no 'likelihood of innocence' anywhere on the page.**

---

## 2. Case two — "Anthony Stark" (a different method)

Behind the alias: a Pennsylvania bite-mark case.

| Field | Value |
|---|---|
| Applicant full name | `Anthony Stark` |
| Offense(s) convicted of | `Aggravated sexual assault` |
| Conviction county / city / state | `Westmoreland County, PA` |
| Court type (state / federal) | `state` |
| Date of conviction | `1991` |
| Sentence received | `45 to 90 years` |
| Record source | Demo — de-identified public cases (offline) |

Click **Flag elements**. Result: a **bite-mark comparison** discredited-forensic
flag. Point out it's the *same machinery* flagging a completely different method,
again anchored to an outside scientific finding — not to the outcome of the case.

---

## 3. Case three — "Steven Rogers" (out-of-state, same rigor)

Behind the alias: a Texas capital case involving microscopic hair comparison.

| Field | Value |
|---|---|
| Applicant full name | `Steven Rogers` |
| Offense(s) convicted of | `Capital murder` |
| Conviction county / city / state | `Harris County, TX` |
| Court type (state / federal) | `state` |
| Date of conviction | `1988` |
| Sentence received | `Life` |
| Record source | Demo — de-identified public cases (offline) |

Click **Flag elements**. Result: another **microscopic hair comparison** flag.
Talking point: the tool doesn't gate on jurisdiction — a flagged element is
checkable regardless of where the case was tried.

---

## 4. The most important 30 seconds — a gap is not a clean bill

Run one more intake with a name the source does **not** contain:

| Field | Value |
|---|---|
| Applicant full name | `Bruce Banner` |
| Offense(s) convicted of | `First-degree murder` |
| Date of conviction | `1990` |
| Record source | Demo — de-identified public cases (offline) |

Click **Flag elements**. The result reports **records searched, nothing matched —
a gap (NOT_FOUND)**, not a clean result. Say: "This is the line the tool is
careful about. A gap in the record is reported as a gap. It never tells you the
case is fine just because it found nothing. Absence of a flag is not absence of a
problem."

---

## 5. Talking points to keep handy

- Every flag is **element-level and checkable** against a source independent of
  guilt or innocence.
- There is **no case-level score and no ranking**, by design — so the tool can't
  be used to sort people into "more" or "less" innocent.
- These three are **real, de-identified public cases**. The person's identity
  never enters the pipeline; it's demo-only data, walled off from anything that
  trains or calibrates the system.

---

## 6. Clean-up (run between or after demos)

**If you only used "Flag elements", there is nothing to clean up** — that path
persists nothing.

If you (or the lawyer) clicked **Save** on any demo case, remove exactly those
saved demo rows with the command below. It is targeted: it only drops case files
whose `source_key` is `demo_marvel`, and it preserves file ownership so the app
keeps working. It never touches real submitted intakes or the exoneration store.

```bash
for i in $(seq 1 8); do ssh -o ConnectTimeout=15 hetzner-web "runuser -u innocence -- python3 - <<'PY'
import json, os
from pathlib import Path
base = Path('/opt/innocence-project-case-scoring/data/processed')
jsonl = base / 'case_files.jsonl'
pdfs = base / 'case_pdfs'
if not jsonl.exists():
    print('no case_files.jsonl; nothing to clean'); raise SystemExit
kept, removed = [], []
for line in jsonl.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    (removed if row.get('source_key') == 'demo_marvel' else kept).append(row)
tmp = jsonl.with_suffix('.jsonl.tmp')
tmp.write_text(''.join(json.dumps(r) + os.linesep for r in kept))
os.replace(tmp, jsonl)
for r in removed:
    p = pdfs / (str(r.get('case_id', '')) + '.pdf')
    if p.exists():
        p.unlink()
print('removed', len(removed), 'demo case file(s); kept', len(kept), 'real one(s)')
PY
" 2>&1 && break; echo "clean-up retry $i"; sleep 3; done
```

The case list refreshes on next load, so no restart is needed. To confirm it's
clean, reload `/cases` in the browser and check no Marvel aliases remain.

---

*Demo data lives in `src/risk_engine/acquisition/demo_marvel.py` (source key
`demo_marvel`) and `data/demo/marvel_intakes.json`. It is demonstration-only and
must never be used as training or label data.*
