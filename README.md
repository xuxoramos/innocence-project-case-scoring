# Project Brief: Case Element Flagging & Intake Support Engine
### A Proof-of-Concept for Innocence Project Case Processing

**Status:** Working proof-of-concept
**Designed for:** Innocence Network intake screening &mdash; built as a Pennsylvania / Allegheny County pilot, jurisdiction-agnostic by design
**Document owner:** [Xuxoramos]

---

*This brief describes the system as it currently stands. The rationale for pivoting away from the original case-scoring concept, and the alternative approaches considered and firmly rejected during scoping, are preserved in [METHODOLOGY_DISCUSSION.md](METHODOLOGY_DISCUSSION.md).*

> **Try it.** A guided walkthrough on the shared demo instance is in
> [docs/demo-guide.md](docs/demo-guide.md). To run the tool locally with your own
> case material (your data never leaves your machine), see
> [docs/local-deployment.md](docs/local-deployment.md).

## 1. Problem Statement

Innocence Project chapters operate a four-stage pipeline: an incarcerated person writes a letter requesting help; the chapter sends an intake questionnaire; the applicant completes it, gathering whatever case records they can obtain from prison clerks or prior counsel; and the chapter screens the resulting material to decide whether to investigate further. The bottleneck is not just volume — it's that screening requires reconstructing and evaluating a case's evidentiary structure from a handwritten questionnaire and a pile of inconsistently organized records, by hand, every time.

This POC proposes a tool to help at the point where the bottleneck actually lives: **processing the intake questionnaire and the records that accompany it**, not scoring historical archives for likely candidates. It does two things:

1. Converts handwritten/inconsistent intake questionnaires into a structured, readable format, and pulls in matching public court records automatically where available.
2. Flags individual, specific elements of the case — a forensic method, a witness identification circumstance, a named prosecutor or judge with a documented history — **each on its own**, rather than producing any single judgment about the case as a whole.

This system does not estimate the probability that a given prisoner is innocent, and it does not rank cases by how easy they would be to win. Both of those framings were considered for earlier versions of this concept and rejected — see [METHODOLOGY_DISCUSSION.md](METHODOLOGY_DISCUSSION.md) for why.

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

## 3. Rejected Approaches

Two framings were considered during scoping and firmly rejected: a case-level **risk score** that ranks cases by similarity to past exonerations (referenced elsewhere in this brief and the specification as **§3.1**), and **synthetic "presumed wrongful" labels** applied to real, still-incarcerated people by feature similarity (**§3.2**). Both remain permanently out of scope and binding on every downstream design decision. The full reasoning — together with the rationale for pivoting away from the original scoring concept — lives in [METHODOLOGY_DISCUSSION.md](METHODOLOGY_DISCUSSION.md).

---

## 4. Scope (POC Phase Only)

**In scope:**
- Intake questionnaire digitization and structuring: convert handwritten/scanned questionnaires into a consistent structured format
- A common intake field schema, built by reviewing publicly available intake questionnaires/screening forms across multiple Innocence Network chapters (not just Pennsylvania) to identify the fields that recur across organizations
- Automated retrieval of matching public court records for a given intake questionnaire, where digitized records exist (via the CourtListener public court-record API); retrieval matches on applicant name and conviction year with no geographic gate, since a flagged element is checkable regardless of where the case was tried
- Element-level flagging applied to whatever records are retrieved (see Section 5), surfaced individually, never combined into a case-level score
- Backfilling the structured intake schema using Innocence Project's own published exoneration case data (innocenceproject.org/all-cases), purely to validate that the schema and extraction pipeline correctly populate from real case material — not to train any outcome-prediction model (see Section 5.2)

**Explicitly out of scope for POC:**
- Any case-level score, rank, or composite judgment of any kind
- Any synthetic labeling of still-incarcerated individuals' cases as likely wrongful (Section 3.2) — permanently out of scope, not just for this phase
- Any automated outreach (FOIA requests, subpoenas, contact with evidence custodians)
- Searching/scanning a historical archive for *new* candidate cases the chapter hasn't received an intake request for — this system processes cases that come in through the existing intake pipeline, it does not go looking for cases on its own
- Integration with case management systems before legal/governance review (Section 9) is complete

---

## 5. How the Tool Works

The tool moves a single incoming intake request through five plain steps and produces a structured packet for an attorney to read. It never collapses that packet into a score.

1. **The intake arrives.** An incarcerated person's completed questionnaire comes in, usually handwritten or scanned.
2. **The tool reads and structures it.** It converts the questionnaire into a consistent, readable format, and records how confident it is in each field it read — so a reviewer can see where the reading was clean and where it was uncertain.
3. **It pulls matching public records.** Where court records have been digitized (via the CourtListener public API), it retrieves the ones that match the applicant, and states plainly which expected records it looked for but could not find.
4. **It flags individual elements.** Against those records it raises specific, separate flags — a discredited forensic method, a named official with a documented history, a witness-identification circumstance, an evidentiary gap — each shown with the exact passage it came from and its own confidence.
5. **It assembles a case packet.** The flags are grouped by type and handed to the attorney, each standing on its own, never summed into a single judgment.

*A technical data-flow diagram of these steps, along with all setup and implementation detail, lives in the companion specification at `docs/spec-v3-triage-assistant.md`.*

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

### 5.3 The Context Each Flag Carries

A flag is more useful when it says not just *that* something is present, but *how much weight the established record already gives it*. Where the tool can determine this from an authoritative source that has nothing to do with the individual defendant's guilt or innocence, it attaches a short piece of context to the individual flag. As with everything else, this context stays attached to that one flag and is never added up into a score.

- **How discredited a forensic method is.** A flagged method is placed in one of three plainly labeled tiers, each tied to the authority that discredited it: methods that have been *formally invalidated or abandoned* (for example, comparative bullet-lead analysis, which the FBI abandoned in 2005, and microscopic hair comparison, which the FBI and Department of Justice found flawed in over 90% of the cases they reviewed in 2015); methods a scientific body found *unvalidated but that courts still use* (the 2009 National Academy of Sciences report and the 2016 PCAST report reached this conclusion for firearms/tool-mark, footwear, and complex DNA-mixture analysis); and methods that are *contested or still evolving* in the literature (pre-1992 arson indicators, the shaken-baby hypothesis, bloodstain-pattern analysis, dog-scent evidence). The tier always names its source, so a reviewer can check it.

- **What kind of official misconduct it is, and how grave.** The misconduct is described by type, using the five categories from the National Registry of Exonerations' study of government misconduct in wrongful convictions: witness tampering, misconduct in interrogations, fabricating evidence, concealing exculpatory evidence in violation of *Brady*, and perjury or false accusation at trial. Fabrication and *Brady* concealment are marked as the gravest; ordinary trial missteps such as an improper closing argument are marked separately as less serious. The specific wording the tool recognizes was drawn from the language courts actually use across a large body of published opinions, so it tracks how misconduct is really described rather than a vocabulary invented for the tool.

- **Whether a named official is a repeat.** When a flag concerns a specific named prosecutor, judge, or analyst, and the tool holds more than one independent, formally documented finding against that same person, it notes the count — a reviewer sees "three separate documented findings," not a vague reputation.

- **How serious the underlying case is.** Where the offense is known, the flag carries the seriousness of the conviction (for example, a homicide or capital case versus a lesser offense), because misconduct concentrates in the most serious cases.

- **Whether the record itself calls the evidence decisive.** When the court record's own words single out a flagged piece of evidence as the only, principal, or case-deciding proof, the tool quotes that passage verbatim alongside the flag. It never characterizes the evidence as decisive on its own — it only shows the record saying so, and leaves the weight to the reviewer.

Each of these is a label a reviewer reads next to a single flag. None is combined with any other, and none produces a case-level number or rank.

### 5.4 Validation Approach for Innocence Project Case Data

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
**Risk:** Digitization and public availability of court records varies widely by jurisdiction, era, and record type; automated retrieval will have gaps the system can't fill.

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

1. **Schema fidelity:** the structuring pipeline correctly converts a representative sample of intake-style material (including IP's own published case narratives, per Section 5.4) into the common schema without losing or distorting case-relevant content.
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

*This brief treats the rejected approaches (§3.1 and §3.2) as a permanent record, not a historical footnote — any future proposal resembling either rejected approach should be checked against the reasoning in [METHODOLOGY_DISCUSSION.md](METHODOLOGY_DISCUSSION.md) before being reconsidered. Sections 5.2 and 6 are treated as binding constraints on every other section. Technical implementation, setup instructions, the system architecture diagram, and reproduction steps live in the companion specification, `docs/spec-v3-triage-assistant.md`.*