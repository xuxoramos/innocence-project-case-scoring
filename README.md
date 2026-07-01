# Project Brief: Case Element Flagging & Intake Support Engine
### A Proof-of-Concept for Innocence Project Case Processing

**Status:** Draft for review (v2 — supersedes case-level scoring approach)
**Target partner:** Pennsylvania Innocence Project (Pittsburgh / Allegheny County pilot)
**Document owner:** [Xuxoramos]

---

## 0. Rationale on pivoting from original version

**Original concept:** Scan historical court archives, score each case on its similarity to past exonerations, and rank cases by likelihood of being a wrongful conviction.

**Why we're moving away from it — three reasons:**

**1. It would have systematically deprioritized the hardest, most neglected cases.**
A score built on similarity to past exonerations rewards cases that look like past *wins* — overwhelmingly, cases with surviving DNA evidence. Categories of wrongful conviction that are common but slow and difficult to overturn, like false confessions with no physical evidence, would have been quietly ranked lower by design, not by oversight. We'd be optimizing the tool to find the easy cases and bury the hard ones — the opposite of where the organization's effort is most needed.

**2. A single score throws away the information attorneys actually need.**
Collapsing a case down to "HIGH risk" or a percentage hides exactly the details that matter for a resourcing decision: which specific piece of evidence is questionable, how confident the system is, and why. We're replacing this with individual, standalone flags — a specific forensic method, a specific witness-identification issue, a specific official's documented history — each shown with its own source and context, never combined into one judgment.

**3. We considered a fix for the bias problem that created a worse problem, and rejected it.**
One option on the table was: find still-incarcerated people whose cases *resemble* past exonerations, and label those cases "likely wrongful" to balance out the training data. We rejected this. It doesn't create independent evidence of anything — it just produces more examples of the same pattern the system already over-weights, with no way to tell a wrongful conviction apart from a correctly decided case that happens to share surface features. Worse, it would mean asserting — with no actual basis — that a specific, real, named person was probably wrongfully convicted. That's not a modeling shortcut; it's a claim about a real person's case that nobody has the standing to make. We're not building anything that does this, in this project or any future version of it.

**What we're building instead:**
A tool focused on the actual bottleneck — processing the intake questionnaire and pulling matching court records — that flags individual, independently verifiable facts (a discredited forensic method, a documented disciplinary history, a specific evidentiary gap) rather than scoring or ranking the case as a whole. Success is measured by whether the tool helps attorneys see relevant facts faster and more clearly, not by whether any specific case is later overturned — since outcomes like that take years to decades, and since policy change or legal precedent can be a meaningful win even without a reversed conviction.

## 1. Problem Statement

Innocence Project chapters operate a four-stage pipeline: an incarcerated person writes a letter requesting help; the chapter sends an intake questionnaire; the applicant completes it, gathering whatever case records they can obtain from prison clerks or prior counsel; and the chapter screens the resulting material to decide whether to investigate further. The bottleneck is not just volume — it's that screening requires reconstructing and evaluating a case's evidentiary structure from a handwritten questionnaire and a pile of inconsistently organized records, by hand, every time.

This POC proposes a tool to help at the point where the bottleneck actually lives: **processing the intake questionnaire and the records that accompany it**, not scoring historical archives for likely candidates. It does two things:

1. Converts handwritten/inconsistent intake questionnaires into a structured, readable format, and pulls in matching public court records automatically where available.
2. Flags individual, specific elements of the case — a forensic method, a witness identification circumstance, a named prosecutor or judge with a documented history — **each on its own**, rather than producing any single judgment about the case as a whole.

This system does not estimate the probability that a given prisoner is innocent, and it does not rank cases by how easy they would be to win. Both of those framings were considered for earlier versions of this concept and rejected — see Section 3 for why.

---

## 2. What This System Is and Is Not

| This system **is** | This system **is not** |
|---|---|
| An intake-processing aid: structuring questionnaires and pulling matching records | A historical-archive scanner that searches for new candidate cases |
| A way to surface individual, independently-checkable facts about a case | A case-level score, rank, or "ease of winning" estimate |
| Built so each flag stands alone, with its own source and confidence | A system that produces any single composite judgment about a case |
| A tool that treats "no flags found" as "no signal," not "no problem" | A tool that asserts innocence, guilt, or likelihood of either |

Every design decision downstream should be traceable to this table. A flag answers one narrow question ("did this case involve hair-microscopy testimony from an analyst whose methodology was later discredited?") and nothing more. It does not, by itself or in combination with other flags, answer "is this case worth taking" — that judgment stays with the attorney.

---

## 3. Rejected Approaches (Read Before Designing Anything Else)

Two earlier approaches to this system were proposed and discarded during scoping. Both are documented here so the reasoning isn't lost if either is revisited later.

### 3.1 Rejected: Case-Level "Risk Score"

An earlier version of this concept proposed scanning a broad historical case archive and assigning each case a composite "Systemic Risk Profile Score," ranking cases by similarity to known exonerations.

**Why this was rejected:**
- A single composite score collapses exactly the information an attorney needs (which specific facts are at issue, how confidently, from what source) into an opaque number that functions like a probability statement regardless of intended framing.
- More importantly: ranking by similarity to *successful* exonerations creates a built-in bias toward cases that are easiest to win — typically those with surviving biological evidence for DNA testing. Categories of wrongful conviction that are common but structurally hard to overturn (false confessions without physical evidence, for example) would be systematically deprioritized by design, not by oversight. A scoring system optimized for "looks like a past win" will quietly bury exactly the cases that don't look like past wins, which are disproportionately the hardest and most neglected cases already.
- Every case has its own evidentiary context; reducing that context to a rank number actively destroys the information needed to make a resourcing decision well.

### 3.2 Rejected: Synthetic Negative Labels via Similarity Matching

A second approach proposed addressing the training-data bias above (Section 3.1) by finding still-incarcerated people whose cases resemble known exonerations on observable features, and labeling those cases as "presumed wrongful conviction" — effectively manufacturing a second class of training examples without requiring an actual exoneration.

**Why this was rejected, and rejected firmly:**
- This does not produce an independent negative class. It produces *more examples of the same pattern the model already over-weights*, because the matching procedure selects on the same surface features the bias already concentrates on. A case matched this way could be wrongful, or could be a correctly decided case where the matching features happen to coincide with an unrelated, confirmed-guilty outcome — there is no way to tell these apart from feature similarity alone, which is precisely why post-conviction investigation exists and takes years.
- This is not a data augmentation technique. It is the manufacture of an unverified, externally consequential claim — "this real, named, still-incarcerated person was likely wrongfully convicted" — based on nothing but pattern resemblance, applied to actual people who have not had that determination made by anyone with the standing to make it. Even held entirely internally for model development, this is a labeling practice the project should not adopt: it creates a paper trail asserting something about real cases that the system has no basis to assert, and that kind of trail does not stay contained to a sandbox by design — model artifacts, intermediate datasets, and validation reports get shared, audited, and reused beyond their original intent.
- It would also produce a validation metric that looks strong but is circular: a test set built from the same similarity logic as the training set will confirm the model finds what it was built to find, telling you nothing about real-world recall.

**What replaced it:** the element-level approach in Section 5, where the unit of analysis is a specific, externally verifiable fact (a forensic method's documented unreliability, a named official's documented disciplinary history) rather than a label asserted about a person's guilt or innocence. See Section 5.2 for how this resolves the same underlying bias problem without the labeling risk.

---

## 4. Scope (POC Phase Only)

**In scope:**
- Intake questionnaire digitization and structuring: convert handwritten/scanned questionnaires into a consistent structured format
- A common intake field schema, built by reviewing publicly available intake questionnaires/screening forms across multiple Innocence Network chapters (not just Pennsylvania) to identify the fields that recur across organizations
- Automated retrieval of matching public court records for a given intake questionnaire, where digitized records exist, limited to Allegheny County, Pennsylvania for the POC
- Element-level flagging applied to whatever records are retrieved (see Section 5), surfaced individually, never combined into a case-level score
- Backfilling the structured intake schema using Innocence Project's own published exoneration case data (innocenceproject.org/all-cases), purely to validate that the schema and extraction pipeline correctly populate from real case material — not to train any outcome-prediction model (see Section 5.2)

**Explicitly out of scope for POC:**
- Any case-level score, rank, or composite judgment of any kind
- Any synthetic labeling of still-incarcerated individuals' cases as likely wrongful (Section 3.2) — permanently out of scope, not just for this phase
- Any jurisdiction outside Allegheny County
- Any automated outreach (FOIA requests, subpoenas, contact with evidence custodians)
- Searching/scanning a historical archive for *new* candidate cases the chapter hasn't received an intake request for — this system processes cases that come in through the existing intake pipeline, it does not go looking for cases on its own
- Integration with case management systems before legal/governance review (Section 9) is complete

---

## 5. System Architecture

```
[Incoming Intake Questionnaire — handwritten/scanned]
        │
        ▼
[OCR + Structuring Layer] ──► confidence score per field
        │
        ▼
[Structured Intake Record] (common schema, Section 5.1)
        │
        ▼
[Automated Public Record Retrieval] (Allegheny County, where digitized)
        │
        ▼
[Element-Level Extraction] ──► confidence score per element
        │
        ├──► [Forensic Method Flags]   (checked against literature/disciplinary record, Section 5.2)
        ├──► [Named Official Flags]    (checked against disciplinary/misconduct record, Section 5.2)
        ├──► [Witness/ID Circumstance Flags]
        └──► [Evidence Preservation Flags]
        │
        ▼
[Individual Flags, Each With Source Passage + Confidence — NEVER combined into a score]
        │
        ▼
[Structured Case Packet for Attorney Review]
```

### 5.1 Common Intake Schema

Built from reviewing publicly available intake/screening questionnaires across multiple chapters (Pennsylvania, Texas, New Jersey, Washington, and the Exoneration Project, among others), the recurring field categories are:

| Category | Example Fields |
|---|---|
| Personal/Background | Name, prisoner number, current facility, conviction jurisdiction and date |
| Conviction Details | Offense type, county/court of conviction, sentence length, co-defendants |
| Claim of Innocence | Narrative of events, claimed role (if any), basis for innocence claim |
| Investigation History | Investigating agency, how applicant became a suspect, other suspects investigated |
| Trial Record | Trial vs. plea, defense counsel, key prosecution evidence and witnesses |
| Post-Conviction History | Direct appeal status, habeas petitions filed, prior PCRA/PDR filings |
| Evidence Availability | What physical/biological evidence exists, its location, whether DNA-testable |
| Materials on Hand | Which records the applicant already has access to (transcripts, police reports, etc.) |

This schema is intentionally built from cross-chapter commonalities rather than designed from scratch, since it needs to be recognizable to intake staff at any chapter, not just the pilot site.

### 5.2 Element Flag Categories and Their Data Sources

This is the section that resolves the bias problem from Section 3 without reintroducing the labeling risk from Section 3.2. The key design choice: **every flag category below is checkable against a source that has nothing to do with any individual defendant's guilt or innocence.**

| Flag Category | What Triggers It | Independent Verification Source |
|---|---|---|
| Discredited Forensic Method | Hair microscopy, bite-mark comparison, arson pour-pattern analysis, or other method named in case record | Forensic science literature, National Academy of Sciences findings, method-specific retraction/critique history — independent of any case outcome |
| Named Official History | A prosecutor, judge, or forensic analyst named in the case record has documented disciplinary action, misconduct findings, or pattern litigation against them | Public disciplinary records, bar association findings, court opinions naming the official — independent of this specific case |
| Informant Testimony Circumstance | Jailhouse informant testimony tied to a sentence reduction or plea deal | The case record itself (this is a directly observable fact pattern, not an inference about reliability) |
| Witness/ID Circumstance | Single-witness conviction, no corroborating physical evidence, identification conditions (lighting, exposure time, cross-racial identification) | The case record itself; cross-racial ID is flagged separately as directly-stated vs. inferred (see Section 6.4) |
| Evidence Preservation Status | Biological evidence collected but not subjected to modern STR DNA testing | The case record / evidence log itself |

Note what's *not* in this table: nothing here requires comparing the case to a set of confirmed exonerations and measuring similarity. The forensic-method and named-official categories are checkable against records that exist independently of whether this particular defendant is guilty or innocent, which is the property that the rejected approach in Section 3.2 lacked entirely. The remaining categories are directly observable facts about the case record, not inferences about outcome likelihood.

**Remaining limitation, stated plainly:** this resolves the *training-bias* problem but does not make the system complete. A case can be wrongful without tripping any of these flags (e.g., a wrongful conviction resting on a witness or official with no documented history of problems, using a forensic method never formally discredited). The system catches *documented, known* failure patterns. It does not catch — and does not claim to catch — wrongful convictions outside those patterns. This is a narrower, more honest claim than the original system made, and it should stay narrow rather than be expanded to imply broader coverage.

### 5.3 Validation Approach for Innocence Project Case Data

Using the Innocence Project's own published exoneration cases (innocenceproject.org/all-cases) for this POC is appropriate for exactly one purpose: confirming that the schema (5.1) and extraction pipeline (5.2) correctly populate from real intake-style material and real court records. The site already publishes structured per-case metadata — contributing cause of conviction, type of forensic science at issue, race of exoneree/victim, plea status, type of crime — which is useful as a **schema validation check** (does our extraction agree with IP's own published categorization of the same case?), not as outcome-prediction training data.

This is a meaningful distinction and the pipeline should be built to respect it: these cases are used to test "did the system correctly extract and structure what's in the record," never "does the system correctly predict that this kind of case gets exonerated." The moment a use of this data starts resembling the latter, it has drifted back toward the rejected approach in Section 3.1.

---

## 6. Known Risks and Required Mitigations

### 6.1 Element Flags Are Necessary But Not Sufficient
**Risk:** Section 5.2 already states this, but it bears repeating as a standing risk rather than a one-time caveat: a clean flag report (nothing triggered) could read to a time-pressed reviewer as "nothing wrong with this case," when it actually means "nothing *matched a known documented pattern*."

**Mitigation:** Every case packet, flagged or not, carries the same scope statement (Section 8) stating explicitly that absence of a flag is not evidence of a correctly decided case.

### 6.2 Volume and Capacity Mismatch
**Risk:** Even without a composite score, if the system surfaces a large number of individually-flagged elements per case, or flags a high proportion of incoming intakes, it adds review burden rather than reducing it for a chapter with limited staff.

**Mitigation:**
- Flags are organized by category in the case packet (Section 8), not as an undifferentiated list, so a reviewer can scan by flag type.
- The POC reports flag frequency per intake (how many flags, on average, per processed questionnaire) before any chapter commits review time, so this is a known quantity, not a surprise.

### 6.3 OCR and Extraction Accuracy on Adversarial Source Material
**Risk:** Handwritten intake questionnaires and older county court records are inconsistently legible and formatted. A missed negation or misread word can invert a flag's meaning (e.g., "comparison was *not* conclusive" read as conclusive).

**Mitigation:**
- Every extracted field and flag carries an OCR-confidence score and an extraction-confidence score, tracked separately.
- No flag appears in the attorney-facing case packet without its verbatim source passage attached for human verification.
- Below a defined confidence floor (set during POC calibration), a flag is withheld rather than shown with a low-confidence label — a missed flag is more recoverable than a misleading one.

### 6.4 Cross-Racial Eyewitness ID Flag Construction
**Risk:** This flag is empirically well-grounded in eyewitness identification research, but extracting "cross-racial" from case text often requires inference rather than a directly stated fact.

**Mitigation:** This flag is split into **directly stated** and **inferred** sub-categories, with inferred instances never displayed with the same weight, and the basis for the inference shown alongside the flag.

### 6.5 Named-Official Flag Sourcing and Fairness
**Risk:** Building a "named official has documented history" flag (Section 5.2) means handling individually identifiable claims about real prosecutors, judges, and analysts. Sourcing needs to be limited to verifiable public disciplinary/misconduct records, not informal reputation or unverified allegation, or the flag becomes a liability rather than an asset — both legally (defamation exposure for the chapter) and substantively (an unreliable flag is worse than no flag).

**Mitigation:**
- This flag category is sourced exclusively from formal records: bar disciplinary actions, court opinions making findings against the named official, official misconduct findings in published exoneration data, or equivalent formal sources.
- The flag always cites its specific source record, not a general claim of "history of misconduct."
- This category is treated as higher-effort and higher-risk than the others in Section 5.2, and should be the first candidate for descoping if POC timeline or sourcing quality is insufficient.

### 6.6 Public Record Retrieval Coverage Is Uneven
**Risk:** Digitization and public availability of Allegheny County court records varies by era and record type; automated retrieval will have gaps the system can't fill.

**Mitigation:** The case packet (Section 8) states explicitly which records were searched for and not found, distinct from records that were searched for and returned no relevant flags — these are different states and should never be visually conflated.

### 6.7 Governance Gap: Handling of Processed Intake Material
**Risk:** Even without case-level scoring, the system now handles real, sensitive intake material — a person's account of their own case, often including personal history beyond the legal facts. This needs a clear data-handling policy, including who can access processed intake records and how long they're retained.

**Mitigation — required before any pilot data leaves the POC environment:**
- A written governance policy, produced jointly with PA Innocence Project leadership and reviewed by counsel, specifying access tiers, retention periods, and handling of any flagged named-official information (Section 6.5) given its defamation-sensitivity.
- Until that policy exists, the POC operates in a closed environment with no output distributed beyond the validation team.

### 6.8 Unconfirmed Staffing and Workflow Fit
**Risk:** This system assumes intake staff and reviewing attorneys will actually use structured output alongside their existing process. That fit has not been confirmed with the chapter.

**Mitigation:** Treated as a dependency to confirm before pilot (Section 9), not a given. The POC can be built and validated against published exoneration case data and sample intake forms without this confirmation, but the pilot phase cannot begin without it.

---

## 7. Output Format

The deliverable per processed intake is a **structured case packet**, not a score or rank. Required elements:

- Structured intake summary (the questionnaire content, organized into the common schema from Section 5.1, in readable form)
- Matched public records found, and explicitly, which expected record types were searched for but not found (Section 6.6)
- Each triggered flag, shown individually, grouped by category (forensic method / named official / witness-ID circumstance / evidence preservation), never combined into a single score
- For each flag: its sub-category where applicable (directly-stated vs. inferred, Section 6.4), its source passage or record, and its confidence score
- A standing scope statement on every packet, flagged or not: *"This packet structures available intake and case record information and flags elements matching documented categories of legal/forensic/procedural concern. It does not assess guilt, innocence, or likelihood of success on appeal. The absence of a flag does not indicate the absence of a problem with the case."*

---

## 8. Required Pre-Pilot Approvals

Before any processed intake data leaves the validation environment in attorney-facing form:

1. Governance policy on intake data handling, access, retention, and named-official flag liability (Section 6.7) — drafted with PA Innocence Project leadership, reviewed by counsel
2. Confirmation that the case packet format fits the chapter's actual intake/screening workflow (Section 6.8)
3. Confirmation of sourcing standards for the named-official flag category (Section 6.5) as sufficiently rigorous to avoid defamation or reliability risk

---

## 9. Success Criteria for POC

The POC is successful if it demonstrates **all** of the following:

1. **Schema fidelity:** the structuring pipeline correctly converts a representative sample of intake-style material (including IP's own published case narratives, per Section 5.3) into the common schema without losing or distorting case-relevant content.
2. **Flag precision on verifiable sources:** forensic-method and named-official flags (Section 5.2) are checked against their cited independent source and confirmed accurate on a manually audited sample — not validated by similarity to past exonerations.
3. **Manageable flag volume:** average flags-per-intake is reported and assessed against actual chapter review capacity, not assumed.
4. **No case-level score leakage:** output review confirms no part of the packet collapses into anything a reviewer would read as a composite judgment.
5. **Governance and workflow-fit dependencies resolved** (Section 8) before any output is shared outside the validation team.

Consistent with the broader reframe of this project, **the POC's success is not measured by whether any flagged case is later overturned.** A useful intake-processing tool, and a defensible flag, both stand on their own regardless of any individual case's eventual outcome — and outcomes of this kind take years to decades to materialize, far outside any POC evaluation window. Likewise, the chapter's eventual definition of "success" for cases it does take on may reasonably include outcomes other than a reversed conviction — a changed evidentiary standard, a policy reform, or a precedent that helps a different case — and this system's job is to support that broader work, not to predict or chase a narrower outcome metric.

---

## 10. Open Questions for Next Phase (Not POC Scope)

- Should the named-official flag category (Section 5.2, 6.5) be built as a shared, cross-chapter resource (a registry of disciplinary records relevant to wrongful conviction work generally), given that the same prosecutors, judges, and analysts often appear across multiple cases and even multiple jurisdictions?
- What does responsible automated public-records outreach (FOIA/subpoena drafting) look like, and should it live in this system or a separately governed tool?
- What is the realistic path to expanding intake processing beyond Allegheny County, given that public record retrieval coverage (Section 6.6) will vary significantly by jurisdiction?
- Is there a legitimate, non-circular way to estimate how many incoming intakes *don't* trip any flag but still warrant investigation — i.e., a way to size the system's blind spot (Section 5.2's stated limitation) without resorting to the rejected approach in Section 3.2?

---

## 11. Reproducing the POC

The repository ships the two inputs the pipeline needs: the code, and a snapshot
of the National Registry of Exonerations at
`data/raw/exonerations/fullcsv.csv`. It also ships the artifact those inputs
produce — the browse/analytics **case store** at
`data/processed/case_store.jsonl` (4,311 confirmed exonerations; 4,278 linked to
a public court record, 33 gaps per Section 6.6). The store is a *derived cache*,
not an input: you can use the shipped copy, or regenerate it yourself.

### 11.1 Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[acquisition]'   # 'acquisition' pulls in requests + pandas
```

### 11.2 Use the shipped case store (fastest)

Nothing to do — `data/processed/case_store.jsonl` is already in the clone. Launch
the browse UI or run flagging directly against it.

### 11.3 Regenerate the case store

There are two backfill paths; both read the shipped NRE snapshot and write the
same `data/processed/case_store.jsonl`.

**API path** — links each exoneration to a court record via the CourtListener
REST API. No large download, but it is network-bound and rate-limited. Set a free
token first:

```bash
export COURTLISTENER_API_TOKEN=...   # from courtlistener.com
risk-engine backfill                 # add --state / --county to scope
```

**Bulk path** — links records from offline CourtListener quarterly snapshots
(no API, no rate limit). This is how the shipped store was built. It needs the
snapshot download (~54 GB compressed for opinions), ~200 GB of scratch space to
stream through, and several hours of compute:

```bash
risk-engine bulk-download            # → data/raw/courtlistener_bulk/
risk-engine backfill --bulk          # streams the snapshots, writes the store
```

Both paths resume by default (already-stored cases are skipped); pass
`--no-resume` to rebuild from scratch. Rows that find no matching court record
are written as **gaps** (Section 6.6), never as clean/negative results.

---

*This brief treats Section 3 (rejected approaches) as a permanent record, not a historical footnote — any future proposal resembling either rejected approach should be checked against the reasoning here before being reconsidered. Sections 5.2 and 6 are treated as binding constraints on every other section.*