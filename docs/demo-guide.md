# Demo Guide — Intake Flagging POC

A short, click-through walkthrough of what the tool does at intake and, just as
importantly, what it refuses to do. It runs against a shared demo instance using
three **real, famous exonerations** and their **real, public-domain court
records** (verbatim appellate opinions from CourtListener). These are confirmed,
public exonerations, so the tool uses the real names; the flagged forensic
content is exactly what the real record says. The demo data is walled off from
anything that trains or calibrates the system.

> **Please don't enter real applicant information into the shared demo instance.**
> It's a public demonstration environment. If you want to try the tool with your
> own case material, run it locally — see [local-deployment.md](local-deployment.md),
> where your data never leaves your own machine.

## 0. Before you start

- Open **https://innocence.thedata.pub** and log in with the credentials shared
  with you.
- Framing to keep in mind: *This tool doesn't decide who's innocent, and it never
  scores or ranks a case. At intake it flags whether the case record contains
  elements matching documented categories of concern, each one checkable against
  an outside source.*

Two buttons matter on the intake form:
- **Flag elements** runs the analysis and shows a packet. It saves **nothing** —
  use this for a quick walkthrough.
- **Save to worklist** keeps the case on the worklist and looks up its court
  records in the background. Use it to show the worklist and the record/docket
  lifecycle. **Saved demo entries reset automatically overnight**, so you can
  re-enter the cases fresh each day.

For every case below, set **Record source** to
**"Demo — famous exonerations (real records, offline)"**.

> **Note on the form fields.** The tool locates a record by the applicant
> **name** and **year of conviction** only (there is no geographic gate), so the
> offense and county boxes are for your notes and won't change what is found.
> Type the values in; they need not appear in the autocomplete list.

---

## 1. Keith Harward — the headline (bite-mark)

Keith Harward was convicted of a 1982 Newport News murder partly on **bite-mark
comparison** testimony and exonerated by DNA in 2016 after 33 years. The record
is his real 1988 Court of Appeals of Virginia opinion.

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
   "This is *why* it's flagged, and it has nothing to do with guilt. It's a
   finding about the method, checkable on its own."
3. The **source passage** quoted from the real opinion — and that there is **no
   score, no rank, no 'likelihood of innocence' anywhere on the page.**

To show the record lifecycle (optional), click **Save to worklist** instead and
open the case from the worklist: the tool retrieved **both the appellate opinion
and the trial-court docket**, and it reports **post-conviction filings** as a
gap — a record it did not retrieve, not a clean bill.

---

## 2. John Norman Huffington — hair + a second flag

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
**Prosecutor misconduct** flag drawn from the same opinion. Each stands on its
own passage and source, and the two are listed separately, never combined into a
single number.

---

## 3. David Chmiel — same method, a Pennsylvania case

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
discredited-forensic flag (plus a witness-identification circumstance). The tool
doesn't gate on jurisdiction — the same method is checkable whether the case was
tried in Virginia, Maryland, or Pennsylvania.

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
a gap**, not a clean result. "A gap in the record is reported as a gap. It never
tells you the case is fine just because it found nothing. Absence of a flag is
not absence of a problem."

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

*Want to try the tool with your own case material? Do not use the shared demo
instance — run it locally, where your data stays on your own machine. See
[local-deployment.md](local-deployment.md). The demo data itself lives in
`src/risk_engine/acquisition/demo_famous.py` and the verbatim opinions under
`data/demo/famous/`; it is demonstration-only and is never used as training or
label data.*
