# Project Brief: Systemic Risk Profile Flagging Engine
### A Proof-of-Concept for Wrongful Conviction Case Triage

**Status:** Draft for review
**Target partner:** Pennsylvania Innocence Project (Pittsburgh / Allegheny County pilot)
**Document owner:** [Xuxoramos]

---

## 1. Problem Statement

Innocence Project chapters face a structural intake bottleneck: the volume of plausible wrongful-conviction cases far exceeds the staff hours available to manually review them. Most chapters, including small regional offices, triage almost entirely by inbound referral and attorney availability, not by systematic review of the historical case pool.

This POC proposes a tool that does **not** estimate the probability that a given prisoner is innocent. Instead, it identifies and ranks cases exhibiting **documented structural failure patterns** — the same categories of error the National Registry of Exonerations (NRE) has already catalogued across thousands of confirmed wrongful convictions. The output is a prioritized worklist for human review, not a determination.

This distinction is not just a framing choice. It is the central design constraint of the entire system, and it is treated as binding for every section below.

---

## 2. What This System Is and Is Not

| This system **is** | This system **is not** |
|---|---|
| A pattern-matching tool against known categories of documented legal error | A predictor of actual innocence |
| A triage and prioritization aid for scarce attorney time | A determination, legal finding, or evidence |
| Trained/validated on cases with confirmed exonerations | Trained on a representative sample of wrongful convictions broadly |
| A way to surface candidates for human investigation | A replacement for human investigation |

Every design decision downstream should be traceable to this table. If a proposed feature would blur this line — for example, displaying a single composite score that reads like a probability — it should be rejected or redesigned.

---

## 3. Core Methodological Limitation (Read Before Designing Anything Else)

The system is validated against NRE exoneration data: cases where a conviction was confirmed wrongful and later overturned. This is the best available ground truth, and it is also a **biased sample of wrongful convictions, not a sample of wrongful convictions in general.**

NRE-documented exonerations systematically over-represent cases that had some independent reason to be revisited: surviving biological evidence amenable to modern DNA testing, capital cases with mandatory appellate review, or media/advocacy attention. They under-represent categories of wrongful conviction that are common but structurally harder to overturn — false confessions without physical evidence being the clearest example.

**Practical consequence:** the model will learn to recognize "the kind of error that, combined with luck, led to a confirmed exoneration." It will not learn to recognize wrongful convictions that lack that paper trail. This is not a bug to be fixed in a later version — it is a permanent property of training on exoneration data, and no amount of additional NRE data resolves it.

**Binding constraints this creates:**

- The system's stated scope (Section 4) must describe what it can find, not what it is trying to find.
- All output (Section 7) must be labeled as a recall-limited tool, with an explicit statement of which case types it is structurally blind to.
- Any future expansion of training data (Section 10) should prioritize sourcing examples of failure modes NRE underrepresents, rather than only adding more NRE cases.

---

## 4. Scope (POC Phase Only)

**In scope:**
- Single jurisdiction: Allegheny County, Pennsylvania (Pittsburgh)
- Historic case types: homicide and sexual assault convictions, pre-2000
- Source material: public court records, transcripts, and dockets already in the public domain
- Output: a ranked worklist of flagged cases with extracted evidence, for human attorney review only
- Validation method: recall testing against a held-out set of already-known Allegheny County exonerations

**Explicitly out of scope for POC:**
- Any other jurisdiction
- Any case type outside homicide/sexual assault
- Any automated outreach (FOIA requests, subpoenas, contact with evidence custodians) — flagged as a future capability only, not built in this phase
- Any output framed as, or convertible into, a probability or likelihood statement
- Integration with case management systems before legal/governance review (Section 8) is complete

---

## 5. System Architecture

```
[Public Court Records, Allegheny County] 
        │
        ▼
[OCR + Text Normalization Layer]  ──► confidence score per document
        │
        ▼
[LLM/NLP Feature Extraction]  ──► confidence score per extracted flag
        │
        ▼
[Tabular Feature Matrix]
        │
        ▼
[Pattern Matching Against NRE-Derived Failure Categories]
        │
        ▼
[Ranked Worklist — NOT a single composite "risk score"]
        │
        ▼
[Mandatory Human Review of Source Passage, Not Just Extracted Flag]
```

Two deliberate departures from the original concept, both required by Sections 3 and 6:

1. **No single composite score.** A unidimensional "HIGH/MEDIUM/LOW" risk label compresses away exactly the information an attorney needs (which flags fired, how confidently, from what source text) and starts to function like a probability statement regardless of intent. The worklist ranks cases but always surfaces the underlying flags and source passages alongside the rank.
2. **Confidence scoring at two separate layers.** OCR confidence and extraction confidence are tracked and surfaced separately, because a low-confidence OCR read feeding into a high-confidence extraction is a different (and more dangerous) failure mode than the reverse. See Section 6.

### 5.1 Feature Flag Categories

| Feature Flag Category | Extraction Target | Known Construction Risk |
|---|---|---|
| Forensic Science Flaws | Hair microscopy, bite-mark matching, arson pour-pattern testimony, named discredited analysts | Generally well-grounded; lower ambiguity in extraction |
| Witness Reliability | Single-witness convictions with no corroborating physical evidence, low-light/short-exposure identification circumstances | Moderate ambiguity in fact-pattern extraction |
| Cross-Racial Eyewitness ID | Cross-racial identification combined with single-witness conviction | **High construction risk — see Section 6.4** |
| Informant Risk | Jailhouse informant testimony tied to a sentence reduction or plea deal | Generally well-grounded |
| Evidence Preservation | Biological evidence collected but not subjected to STR DNA testing, with evidence locker reference | Depends on chain-of-custody record completeness, which is inconsistent |

---

## 6. Known Risks and Required Mitigations

### 6.1 Training/Validation Bias (see Section 3)
**Mitigation:** Scope and output labeling constraints as specified above. No mitigation eliminates this risk; it is structural.

### 6.2 Base Rate / Triage Capacity Mismatch
A flagging system tuned for sensitivity will likely flag a meaningful share of any large historical case pool as worthy of review. Allegheny County's Innocence Project presence is a small staff. If the POC produces hundreds of "high-priority" flags, it is not useful — it has just relocated the bottleneck.

**Mitigation:**
- The POC must report, before any chapter staff time is committed, the projected flag volume at varying sensitivity thresholds.
- The ranked worklist (not a binary flag) allows the chapter to set their own review capacity as a cutoff, rather than the system dictating what counts as "high."
- Success criteria for the POC (Section 9) include flag volume feasibility, not just flag accuracy.

### 6.3 OCR and Extraction Accuracy on Adversarial Source Text
1980s–90s county records are inconsistently scanned, sometimes handwritten, and inconsistently formatted across courtrooms and stenographers. A single missed negation ("expert testified the comparison was *not* conclusive") inverts a flag's meaning.

**Mitigation:**
- Every extracted flag carries an OCR-confidence score and an extraction-confidence score, tracked separately.
- No flag is included in attorney-facing output without the underlying source passage attached, verbatim, for human verification before any action is taken.
- Below a defined confidence floor (to be set during POC calibration), flags are not surfaced at all rather than surfaced with a low-confidence label — a missed flag is a more recoverable failure than a misleading one at this stage.

### 6.4 Cross-Racial Eyewitness ID Flag Construction
This flag category is empirically well-supported in eyewitness identification research, but extracting "cross-racial" from historical court text is itself risky: it generally requires inferring race from sparse, inconsistent transcript language rather than a directly stated fact.

**Mitigation:**
- This flag is split into two sub-categories with different confidence treatment: **directly stated** (e.g., explicit description in testimony) versus **inferred** (e.g., inferred from other transcript context).
- Inferred instances are never displayed with the same visual/ranking weight as directly stated ones, and the inference basis is shown alongside the flag.

### 6.5 Human-in-the-Loop Labor Cost Is Understated in the Original Concept
"Intern validation against physical files" undersells the actual difficulty of retrieving 30-year-old evidence logs, chain-of-custody records, and archived transcripts — a slow process that sometimes meets institutional resistance from custodians of the records.

**Mitigation:**
- The POC's success criteria are decoupled from physical file retrieval. The POC's job is to demonstrate the *flagging pipeline* works against records that are already digitized/public; physical record retrieval is treated as a separate, later-phase capability with its own resourcing question, not an assumed input to this phase.
- Any future phase that depends on physical record retrieval needs its own feasibility check with the chapter before being added to scope.

### 6.6 Governance Gap: Who Owns a Flag on an Unrepresented Case
If the system flags a historical case where no attorney-client relationship exists, the system has created information with unclear ownership and unclear duty. There is also downstream legal exposure to consider: a flag could in principle become relevant in litigation about how the organization allocates review resources.

**Mitigation — required before any pilot data leaves the POC environment:**
- A written governance policy, produced jointly with PA Innocence Project leadership and ideally reviewed by counsel, must specify: who receives flags, what retention period applies, whether/how a flag creates any obligation to act, and how flags are documented internally.
- Until that policy exists, the POC operates in a closed environment with no attorney-facing output distributed beyond the validation team.

### 6.7 Unconfirmed Staffing Assumption
The original concept assumes Pittsburgh-based PA Innocence Project staff (housed at Duquesne University's School of Law) will serve as the human validation layer. This has not been confirmed.

**Mitigation:** This brief treats chapter staff availability as a **dependency to be confirmed**, not a given. POC planning (Section 9) proceeds in parallel with — not contingent on — that confirmation, but the pilot review phase cannot begin until it is secured in writing.

### 6.8 False Negative / False Positive Cost Asymmetry
The system will inevitably miss real wrongful convictions that don't match historical NRE-documented patterns (Section 3), while also raising false positives among cases that match patterns but were correctly decided.

**Mitigation:** The system is explicitly tuned to minimize false negatives among the case types it can see (favoring sensitivity over precision within scope), on the reasoning that a missed case has a much higher human cost than an extra hour of attorney review that turns up nothing. This tradeoff is stated here so it is a documented design decision, not an emergent and unexamined property of the model.

---

## 7. Output Format

Attorney-facing output is a structured case brief, not a black-box score. Required elements per flagged case:

- Case identifier and jurisdiction/year
- Each triggered flag, individually, with its sub-category (e.g., directly-stated vs. inferred for 6.4)
- OCR confidence and extraction confidence for each flag, shown separately
- The verbatim source passage supporting each flag
- A relative rank within the current worklist batch — **never** a standalone composite score
- An explicit statement of scope limitation: "This case was flagged based on pattern similarity to documented exoneration categories. This is not a determination of innocence, and the absence of a flag does not indicate the absence of error."

---

## 8. Required Pre-Pilot Approvals

Before any case data leaves the validation environment in attorney-facing form:

1. Governance policy on flag ownership, retention, and duty to act (Section 6.6) — drafted with PA Innocence Project leadership, reviewed by counsel
2. Written confirmation of Pittsburgh chapter staff availability for the human review layer (Section 6.7)
3. Sign-off from chapter leadership on the projected flag-volume estimate (Section 6.2) as feasible given current staffing

---

## 9. Success Criteria for POC

The POC is successful if, and only if, it demonstrates **all** of the following — accuracy alone is not sufficient:

1. **Recall on known cases:** the pipeline correctly flags a high proportion of already-confirmed Allegheny County exonerations in the pre-2000 homicide/sexual assault pool.
2. **Feasible flag volume:** the projected number of "review-worthy" flags at the chosen sensitivity threshold is realistic against actual chapter review capacity (a number, not an assumption).
3. **Confidence calibration:** OCR and extraction confidence scores meaningfully track actual error rates on a manually audited sample, rather than being uniformly high or uninformative.
4. **No misleading single-score behavior:** output review confirms the worklist format does not collapse into something attorneys read as a probability statement.
5. **Governance and staffing dependencies resolved** (Section 8) before any case-level data is shared outside the validation team.

---

## 10. Open Questions for Next Phase (Not POC Scope)

- How should the system handle case types this POC excludes (non-homicide, non-sexual-assault, post-2000)?
- Can additional training signal for underrepresented failure modes (e.g., false-confession cases without DNA exoneration) be sourced from sources other than NRE, to partially offset the bias in Section 3? This is a research question, not a planned feature.
- What does a responsible automated-outreach capability (FOIA/subpoena drafting) look like, and does it belong in this system at all, or in a separate tool gated by its own governance review?
- What is the realistic path to expanding beyond a single jurisdiction, and does the "bad actor clustering" effect (same detective/prosecutor/lab tech across multiple cases) justify prioritizing adjacent jurisdictions where those same individuals may have worked?

---

*This brief treats Sections 3 and 6 as binding constraints on every other section, not as caveats appended after the fact. Any future revision that changes scope, output format, or success criteria should be checked against those sections before being adopted.*

---

## 11. Repository Scaffold (POC)

The codebase mirrors the pipeline in Section 5, with every processing step
optional so already-digitized cases can skip OCR/text/tabular extraction:

```
src/risk_engine/
  models.py            Domain types: Case, Document, Flag (separate OCR/extraction confidence), Worklist
  config.py            Confidence floor + paths
  acquisition/         Multi-jurisdiction sources (registry). Pittsburgh = allegheny_pa; add small cities here
  processing/          Optional, composable steps: OCR → text → tabular (pipeline runs only what applies)
  scoring/             Swappable ranking algorithms (registry) to A/B test learning models; baseline = flag_count
  ui/app.py            Streamlit UI: navigate acquired → OCR/text → tabular, with flags, confidences, source passages, relative rank only
  cli.py               Wires acquisition → processing → scoring
tests/                 End-to-end + unit tests
```

Run: `pip install -e .[dev]` then `pytest`. CLI: `risk-engine --jurisdiction allegheny_pa --scorer flag_count`. UI: `pip install -e .[ui]` then `streamlit run src/risk_engine/ui/app.py`.
