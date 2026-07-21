# Local Deployment — run the tool with your own data

The shared demo instance at `https://innocence.thedata.pub` is for the public
walkthrough only. **If your chapter wants to try the tool with real case
material, run it locally.** When you self-host, your data stays on your own
machine — the only network calls the tool makes are optional public court-record
lookups you explicitly enable (CourtListener).

This is a proof-of-concept, not production software. Treat it accordingly: run it
on a machine you control, and review the governance notes in the
[README](../README.md) and [METHODOLOGY_DISCUSSION](../METHODOLOGY_DISCUSSION.md)
first.

## 1. Prerequisites

- Python 3.11 or newer
- `git`

## 2. Install

```bash
git clone https://github.com/xuxoramos/innocence-project-case-scoring.git
cd innocence-project-case-scoring
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[ui]"              # add ,ocr,acquisition for OCR + live retrieval
```

## 3. Set a login (optional but recommended)

The web UI supports HTTP basic auth. If you set both variables it is enforced; if
you leave them unset, the app runs open on localhost (fine for a single-user
laptop trial).

```bash
export RISK_ENGINE_AUTH_USER=yourname
export RISK_ENGINE_AUTH_PASSWORD='choose-a-strong-password'
```

## 4. (Optional) live court-record retrieval

Without this, use the offline demo source. To pull real appellate opinions from
CourtListener, get a free API token at
`https://www.courtlistener.com/profile/api-token/` and export it:

```bash
export COURTLISTENER_API_TOKEN=your_token_here
```

## 5. Run

```bash
python -m risk_engine.ui
```

Open `http://127.0.0.1:8000`. Fill in an intake (or upload an intake PDF),
choose a **Record source**, and click **Flag elements** for an ephemeral packet
or **Save to worklist** to keep it and look up records.

## 6. Where your data lives

- Everything persists to a local SQLite database at `data/processed/app.db` on
  your machine. Nothing is uploaded anywhere.
- The only outbound calls are the CourtListener API lookups you enable in step 4.
  If you never set a token and use the offline demo source, the tool makes no
  network calls at all.
- To start clean, stop the app and delete `data/processed/app.db` (it is
  regenerated on next run; the confirmed-exoneration reference store is rebuilt
  from the shipped data).

## 7. Governance reminders

- The tool flags **individual, checkable elements**; it never scores or ranks a
  case, and "no flags" is not a clean bill (a gap is reported as a gap).
- Do not put real applicant information into the shared demo instance — that is
  exactly what this local mode is for.
