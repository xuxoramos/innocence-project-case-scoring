"""Common Innocence Network intake schema (README v2 Section 5.1).

This is the cross-chapter *field catalog* — the "database" of intake fields that
recur across Innocence Network organizations. It was built by reviewing the
publicly available intake/application questionnaires and eligibility pages of
five chapters (see ``CHAPTER_SOURCES``), exactly as README v2 Section 5.1
prescribes: built from cross-chapter commonalities rather than designed from
scratch, so it is recognizable to intake staff at any chapter.

Nothing here scores, ranks, or judges a case. It only describes *what fields a
structured intake record can hold* and where each field came from, so the
structuring layer (``intake.structuring``) has a target schema and every field
is traceable to a real source form.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class IntakeCategory(str, enum.Enum):
    """The eight recurring field groups from README v2 Section 5.1.

    ``AUTHORIZATION`` is an empirically-recurring ninth group (release/consent
    forms appear in the Exoneration Project and Texas processes); it extends the
    eight named in 5.1 because it is a genuine cross-chapter commonality.
    """

    PERSONAL_BACKGROUND = "personal_background"
    CONVICTION_DETAILS = "conviction_details"
    CLAIM_OF_INNOCENCE = "claim_of_innocence"
    INVESTIGATION_HISTORY = "investigation_history"
    TRIAL_RECORD = "trial_record"
    POST_CONVICTION_HISTORY = "post_conviction_history"
    EVIDENCE_AVAILABILITY = "evidence_availability"
    MATERIALS_ON_HAND = "materials_on_hand"
    AUTHORIZATION = "authorization"


class Universality(str, enum.Enum):
    """How widely a field recurs across the surveyed chapters."""

    NEAR_UNIVERSAL = "near_universal"  # appears, in some form, across most orgs
    CHAPTER_SPECIFIC = "chapter_specific"  # only one or two chapters ask it


# Chapter codes -> (display name, citable source URL). Provenance for every
# field below, so the schema can be defended as built from real forms.
CHAPTER_SOURCES: dict[str, tuple[str, str]] = {
    "PA": ("Pennsylvania Innocence Project (pilot)", "https://www.painnocence.org/request-help"),
    "IP": ("The Innocence Project (national)", "https://innocenceproject.org/submit-case/"),
    "EP": (
        "The Exoneration Project",
        "https://www.exonerationproject.org/what-we-do/request-help/",
    ),
    "TX": ("Innocence Project of Texas", "https://innocencetexas.org/submit-a-case/"),
    "MIP": ("Midwest Innocence Project", "https://themip.org/submit-a-case/"),
}


@dataclass(frozen=True)
class FieldSpec:
    """One field in the common intake schema, with its provenance."""

    key: str
    label: str
    category: IntakeCategory
    universality: Universality
    sources: tuple[str, ...]  # chapter codes from CHAPTER_SOURCES
    notes: str = ""

    @property
    def is_near_universal(self) -> bool:
        return self.universality is Universality.NEAR_UNIVERSAL


_U = Universality.NEAR_UNIVERSAL
_C = Universality.CHAPTER_SPECIFIC

# The catalog. Order is by category, then near-universal fields first.
COMMON_INTAKE_SCHEMA: tuple[FieldSpec, ...] = (
    # -- Personal / Background -------------------------------------------
    FieldSpec("applicant_full_name", "Applicant full name",
              IntakeCategory.PERSONAL_BACKGROUND, _U, ("PA", "IP", "EP", "TX", "MIP")),
    FieldSpec("inmate_doc_id", "Inmate / DOC identification number",
              IntakeCategory.PERSONAL_BACKGROUND, _U, ("IP", "EP", "TX"),
              notes="'Inmate number' (IP), 'Identification No.' (EP); TDCJ number (TX)."),
    FieldSpec("current_facility", "Current facility",
              IntakeCategory.PERSONAL_BACKGROUND, _U, ("PA", "IP", "EP")),
    FieldSpec("current_address", "Current mailing address",
              IntakeCategory.PERSONAL_BACKGROUND, _U, ("IP", "EP")),
    FieldSpec("date_of_birth", "Date of birth",
              IntakeCategory.PERSONAL_BACKGROUND, _C, ("EP",)),
    FieldSpec("preferred_language", "Preferred language",
              IntakeCategory.PERSONAL_BACKGROUND, _C, ("EP",)),
    FieldSpec("race_ethnicity", "Race / ethnicity",
              IntakeCategory.PERSONAL_BACKGROUND, _C, ("EP",),
              notes="Self-reported; relevant to cross-racial ID flag (README 6.4)."),
    FieldSpec("highest_grade_completed", "Highest grade completed in school",
              IntakeCategory.PERSONAL_BACKGROUND, _C, ("EP",)),
    # -- Conviction Details ----------------------------------------------
    FieldSpec("offense_convicted_of", "Offense(s) convicted of",
              IntakeCategory.CONVICTION_DETAILS, _U, ("PA", "IP", "EP", "TX")),
    FieldSpec("conviction_jurisdiction", "Conviction county / city / state",
              IntakeCategory.CONVICTION_DETAILS, _U, ("IP", "EP"),
              notes="Geographic gate for every chapter."),
    FieldSpec("court_type", "Court type (state / federal)",
              IntakeCategory.CONVICTION_DETAILS, _U, ("PA",),
              notes="PA accepts state OR federal; most chapters are state-court only."),
    FieldSpec("date_of_conviction", "Date of conviction",
              IntakeCategory.CONVICTION_DETAILS, _U, ("IP", "EP")),
    FieldSpec("sentence_received", "Sentence received",
              IntakeCategory.CONVICTION_DETAILS, _U, ("IP", "EP")),
    FieldSpec("case_number", "Case number of conviction",
              IntakeCategory.CONVICTION_DETAILS, _C, ("EP",)),
    FieldSpec("co_defendants", "Co-defendants",
              IntakeCategory.CONVICTION_DETAILS, _C, ("EP",)),
    FieldSpec("time_left_to_serve", "Time left to serve",
              IntakeCategory.CONVICTION_DETAILS, _C, ("MIP",),
              notes="Midwest IP gate (>10 years remaining); others have no minimum."),
    # -- Claim of Innocence ----------------------------------------------
    FieldSpec("claims_actual_innocence", "Claims actual innocence",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("PA", "IP", "EP", "TX", "MIP"),
              notes="Universal hard eligibility gate."),
    FieldSpec("innocence_scope", "Scope of innocence claim (all charges?)",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("PA", "IP")),
    FieldSpec("innocence_rationale", "Basis for the innocence claim",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("PA", "IP", "EP")),
    FieldSpec("applicant_whereabouts_activity", "Whereabouts / activity at time of crime",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("IP", "EP"),
              notes="The alibi field."),
    FieldSpec("prosecution_narrative", "What police / prosecutors say happened",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("PA", "IP", "EP")),
    FieldSpec("victim_names", "Victim name(s)",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("IP", "EP")),
    FieldSpec("relationship_to_victim", "Relationship to victim",
              IntakeCategory.CLAIM_OF_INNOCENCE, _C, ("IP",)),
    FieldSpec("applicant_theory", "Applicant's account of what happened",
              IntakeCategory.CLAIM_OF_INNOCENCE, _U, ("IP", "EP")),
    # -- Investigation History -------------------------------------------
    FieldSpec("crime_date_time", "Date / time the crime occurred",
              IntakeCategory.INVESTIGATION_HISTORY, _U, ("IP", "EP")),
    FieldSpec("investigating_agency", "Investigating agency",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("PA",),
              notes="Named in README 5.1; not on most posted forms."),
    FieldSpec("how_became_suspect", "How the applicant became a suspect",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("PA", "EP")),
    FieldSpec("other_suspects", "Other suspects investigated",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("PA",)),
    FieldSpec("date_of_arrest", "Date of arrest",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("IP",)),
    FieldSpec("date_crime_reported", "Date the crime was reported",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("IP",)),
    FieldSpec("crime_location", "Where the crime occurred",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("EP",)),
    FieldSpec("eyewitness_identification_method", "Eyewitness ID method (line-up / photo / show-up)",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("EP",),
              notes="Feeds witness/ID-circumstance flag (README 5.2)."),
    FieldSpec("police_interviews", "Police interviews (length, who involved)",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("EP",)),
    FieldSpec("statements_to_police", "Statements to police and how recorded",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("EP",)),
    FieldSpec("attorney_present_at_arrest", "Attorney present at arrest",
              IntakeCategory.INVESTIGATION_HISTORY, _C, ("EP",)),
    # -- Trial Record ----------------------------------------------------
    FieldSpec("disposition_type", "Disposition (jury / bench / guilty plea / no contest)",
              IntakeCategory.TRIAL_RECORD, _U, ("PA", "EP"),
              notes="Guilty-plea handling is a key eligibility dimension."),
    FieldSpec("defense_counsel", "Defense counsel",
              IntakeCategory.TRIAL_RECORD, _C, ("PA",)),
    FieldSpec("key_prosecution_evidence", "Key prosecution evidence and witnesses",
              IntakeCategory.TRIAL_RECORD, _U, ("IP", "EP")),
    FieldSpec("case_against_at_trial", "The case against the applicant at trial",
              IntakeCategory.TRIAL_RECORD, _C, ("EP",)),
    FieldSpec("defense_at_trial", "The defense presented at trial",
              IntakeCategory.TRIAL_RECORD, _C, ("EP",)),
    FieldSpec("exculpatory_not_presented", "Evidence of innocence available but not presented",
              IntakeCategory.TRIAL_RECORD, _C, ("EP",)),
    FieldSpec("witnesses_not_called", "Witnesses available but not called",
              IntakeCategory.TRIAL_RECORD, _C, ("EP",)),
    FieldSpec("applicant_testified", "Did the applicant testify, and what they said",
              IntakeCategory.TRIAL_RECORD, _C, ("EP",)),
    # -- Post-Conviction History -----------------------------------------
    FieldSpec("appeals_status", "Direct appeal status",
              IntakeCategory.POST_CONVICTION_HISTORY, _U, ("PA", "IP", "TX", "MIP"),
              notes="Appeals-exhaustion gate."),
    FieldSpec("currently_represented", "Currently represented by counsel",
              IntakeCategory.POST_CONVICTION_HISTORY, _U, ("PA", "MIP"),
              notes="PA: no attorney / no right to appointed counsel."),
    FieldSpec("postconviction_filings", "Post-conviction filings (PCRA / habeas / PDR)",
              IntakeCategory.POST_CONVICTION_HISTORY, _C, ("EP",),
              notes="Type, case number, date filed, claims, decision, attorney."),
    # -- Evidence Availability -------------------------------------------
    FieldSpec("biological_dna_evidence_exists", "DNA-testable biological evidence exists",
              IntakeCategory.EVIDENCE_AVAILABILITY, _C, ("IP",),
              notes="National IP's defining hard gate; not required by other chapters."),
    FieldSpec("dna_evidence_description", "Description of biological / DNA evidence",
              IntakeCategory.EVIDENCE_AVAILABILITY, _C, ("IP",)),
    FieldSpec("evidence_location", "Location of physical / biological evidence",
              IntakeCategory.EVIDENCE_AVAILABILITY, _C, ("IP",)),
    FieldSpec("new_evidence_since_trial", "New evidence not used at trial",
              IntakeCategory.EVIDENCE_AVAILABILITY, _C, ("EP",)),
    FieldSpec("untested_physical_evidence", "Untested / unfound physical evidence",
              IntakeCategory.EVIDENCE_AVAILABILITY, _C, ("EP",),
              notes="Feeds evidence-preservation flag (README 5.2)."),
    # -- Materials on Hand -----------------------------------------------
    FieldSpec("records_on_hand", "Records the applicant already has",
              IntakeCategory.MATERIALS_ON_HAND, _U, ("PA", "EP"),
              notes="Transcripts, police reports, etc."),
    FieldSpec("accessible_documents_contacts", "Accessible documents and who holds them",
              IntakeCategory.MATERIALS_ON_HAND, _C, ("EP",)),
    FieldSpec("authorized_supporter_contact", "Authorized supporter contact",
              IntakeCategory.MATERIALS_ON_HAND, _C, ("EP",)),
    # -- Authorization (extends 5.1) -------------------------------------
    FieldSpec("release_consent", "Records-release / contact consent",
              IntakeCategory.AUTHORIZATION, _U, ("EP", "TX"),
              notes="Near-universal in practice; collected at varying stages."),
)


@dataclass(frozen=True)
class EligibilityGate:
    """A screening dimension chapters use to decide whether to review a case.

    These are *not* intake content fields and never combine into a score; they
    are the recurring decision gates, kept separate so the structuring layer can
    surface them without implying any case-level judgment.
    """

    key: str
    label: str
    sources: tuple[str, ...]
    notes: str = ""


ELIGIBILITY_GATES: tuple[EligibilityGate, ...] = (
    EligibilityGate("actual_innocence_claim", "Claims actual innocence",
                    ("PA", "IP", "EP", "TX", "MIP"), "Universal hard gate."),
    EligibilityGate("conviction_completed", "Convicted (not merely arrested / charged)",
                    ("PA", "IP", "EP", "TX", "MIP")),
    EligibilityGate("jurisdiction_match", "Conviction within the chapter's jurisdiction",
                    ("PA", "IP", "EP", "TX", "MIP"),
                    "PA: PA state+federal; TX: Texas felony; MIP: MO/KS/IA/NE/AR; "
                    "EP: anywhere in US; IP: US except AZ/CA/IL/MI/OH."),
    EligibilityGate("appeals_exhausted_or_unrepresented", "Appeals exhausted / not represented",
                    ("PA", "IP", "TX", "MIP")),
    EligibilityGate("dna_biological_evidence_available", "DNA-testable biological evidence exists",
                    ("IP",), "National IP only."),
    EligibilityGate("sentence_threshold", "Enough sentence remaining",
                    ("MIP",), "Midwest IP: >10 years remaining."),
    EligibilityGate("guilty_plea_accepted", "Guilty / no-contest pleas accepted",
                    ("PA", "EP"), "EP and PA accept pleas; National IP requires trial+appeal."),
    EligibilityGate("excluded_offense_type", "Offense type not on the exclusion list",
                    ("IP", "EP"), "National IP excludes nine case types; EP excludes "
                    "self-defense / excessive-sentence / sufficiency claims."),
)


# -- convenience accessors -----------------------------------------------

_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in COMMON_INTAKE_SCHEMA}


def field_by_key(key: str) -> FieldSpec:
    """Return the FieldSpec for ``key`` or raise KeyError."""
    return _BY_KEY[key]


def fields_for(category: IntakeCategory) -> tuple[FieldSpec, ...]:
    """All fields in a category, in catalog order."""
    return tuple(f for f in COMMON_INTAKE_SCHEMA if f.category is category)


def near_universal_fields() -> tuple[FieldSpec, ...]:
    """Fields that recur across most chapters (the portable core)."""
    return tuple(f for f in COMMON_INTAKE_SCHEMA if f.is_near_universal)
