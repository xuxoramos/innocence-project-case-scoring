# Methodology Discussion: Pivot Rationale & Rejected Approaches

**Companion to:** the project brief in [README.md](README.md).

**Purpose:** This document preserves the reasoning that sits *behind* the current
design — why the project pivoted away from its original case-scoring concept, and
which alternative approaches were considered and firmly rejected during scoping. It is
kept separate so the README describes only the current state of the system, while this
record ensures the reasoning is not lost if any rejected approach is revisited later.

The two rejected approaches below are referenced throughout the README and the technical
specification by their canonical labels, **§3.1** (case-level risk score) and **§3.2**
(synthetic negative labels). Both remain **permanently out of scope and binding** on all
downstream design.

---

## 1. Why We Pivoted from the Original Version

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

---

## 2. Rejected Approaches (Read Before Designing Anything Else)

Two earlier approaches to this system were proposed and discarded during scoping. Both are documented here so the reasoning isn't lost if either is revisited later.

### §3.1 Rejected: Case-Level "Risk Score"

An earlier version of this concept proposed scanning a broad historical case archive and assigning each case a composite "Systemic Risk Profile Score," ranking cases by similarity to known exonerations.

**Why this was rejected:**
- A single composite score collapses exactly the information an attorney needs (which specific facts are at issue, how confidently, from what source) into an opaque number that functions like a probability statement regardless of intended framing.
- More importantly: ranking by similarity to *successful* exonerations creates a built-in bias toward cases that are easiest to win — typically those with surviving biological evidence for DNA testing. Categories of wrongful conviction that are common but structurally hard to overturn (false confessions without physical evidence, for example) would be systematically deprioritized by design, not by oversight. A scoring system optimized for "looks like a past win" will quietly bury exactly the cases that don't look like past wins, which are disproportionately the hardest and most neglected cases already.
- Every case has its own evidentiary context; reducing that context to a rank number actively destroys the information needed to make a resourcing decision well.

### §3.2 Rejected: Synthetic Negative Labels via Similarity Matching

A second approach proposed addressing the training-data bias above (§3.1) by finding still-incarcerated people whose cases resemble known exonerations on observable features, and labeling those cases as "presumed wrongful conviction" — effectively manufacturing a second class of training examples without requiring an actual exoneration.

**Why this was rejected, and rejected firmly:**
- This does not produce an independent negative class. It produces *more examples of the same pattern the model already over-weights*, because the matching procedure selects on the same surface features the bias already concentrates on. A case matched this way could be wrongful, or could be a correctly decided case where the matching features happen to coincide with an unrelated, confirmed-guilty outcome — there is no way to tell these apart from feature similarity alone, which is precisely why post-conviction investigation exists and takes years.
- This is not a data augmentation technique. It is the manufacture of an unverified, externally consequential claim — "this real, named, still-incarcerated person was likely wrongfully convicted" — based on nothing but pattern resemblance, applied to actual people who have not had that determination made by anyone with the standing to make it. Even held entirely internally for model development, this is a labeling practice the project should not adopt: it creates a paper trail asserting something about real cases that the system has no basis to assert, and that kind of trail does not stay contained to a sandbox by design — model artifacts, intermediate datasets, and validation reports get shared, audited, and reused beyond their original intent.
- It would also produce a validation metric that looks strong but is circular: a test set built from the same similarity logic as the training set will confirm the model finds what it was built to find, telling you nothing about real-world recall.

**What replaced it:** the element-level approach in README Section 5, where the unit of analysis is a specific, externally verifiable fact (a forensic method's documented unreliability, a named official's documented disciplinary history) rather than a label asserted about a person's guilt or innocence. See README Section 5.2 for how this resolves the same underlying bias problem without the labeling risk.

---

*This record treats both rejected approaches as permanent, not as historical footnotes: any future proposal resembling either one should be checked against the reasoning above before it is reconsidered.*
