"""Core domain models shared across acquisition and processing.

These are plain ``dataclasses`` (stdlib only) so the pipeline can be imported
and tested without optional, heavy dependencies. They encode the design
constraints from README v2:

* Confidence is tracked separately for OCR and extraction (README 5.2 / 6.3).
* Each flag carries its verbatim source passage for human verification.
* No single composite score and no ranking — a case carries the flat list of
  its flags, each one standalone and never combined (README v2 Section 7).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class FlagCategory(str, enum.Enum):
    """Element-flag categories (README v2 Section 5.2).

    Each is checkable against a source independent of the defendant's guilt: the
    discredited-method and official-misconduct categories against an external
    record (forensic literature / disciplinary or misconduct finding), the rest
    against directly observable facts in the case record. Official misconduct is
    split by role — prosecutor, judge, police, and forensic-analyst/expert — so
    each can be calibrated against its own NRE factor column (Section 6.5), plus
    an ``OTHER_OFFICIAL_MISCONDUCT`` bucket for officials outside those four
    roles (e.g. child-welfare or corrections staff) so a formally-sourced finding
    is never dropped just because the actor doesn't fit a named role (spec v3
    §3.3). The category set is intentionally data-driven and extensible: adding a
    category is an enum edit, and routing a role to it is a data edit in
    ``officials._ROLE_KEYWORDS`` — no flagger internals change.
    Cross-racial identification is not its own category — it is a
    ``WITNESS_ID_CIRCUMSTANCE`` flagged with an ``INFERRED`` basis (Section 6.4).
    """

    DISCREDITED_FORENSIC_METHOD = "discredited_forensic_method"
    PROSECUTOR_MISCONDUCT = "prosecutor_misconduct"
    JUDICIAL_MISCONDUCT = "judicial_misconduct"
    POLICE_MISCONDUCT = "police_misconduct"
    EXPERT_WITNESS_MISCONDUCT = "expert_witness_misconduct"
    OTHER_OFFICIAL_MISCONDUCT = "other_official_misconduct"
    INFORMANT_CIRCUMSTANCE = "informant_circumstance"
    WITNESS_ID_CIRCUMSTANCE = "witness_id_circumstance"
    EVIDENCE_PRESERVATION = "evidence_preservation"


class FlagBasis(str, enum.Enum):
    """How a flag was established. Inferred flags are weighted lower (README 6.4)."""

    DIRECTLY_STATED = "directly_stated"
    INFERRED = "inferred"


class ProcessingStage(str, enum.Enum):
    """Stages a case document may pass through; each is optional."""

    ACQUIRED = "acquired"
    OCR = "ocr"
    TEXT = "text"
    TABULAR = "tabular"


@dataclass
class Document:
    """A single source document for a case (transcript, docket, etc.)."""

    doc_id: str
    case_id: str
    source_uri: str = ""
    media_type: str = "application/pdf"
    needs_ocr: bool = True
    raw_path: str | None = None
    ocr_text: str | None = None
    ocr_confidence: float | None = None
    normalized_text: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def stage(self) -> ProcessingStage:
        if self.normalized_text is not None:
            return ProcessingStage.TEXT
        if self.ocr_text is not None:
            return ProcessingStage.OCR
        return ProcessingStage.ACQUIRED


@dataclass
class Flag:
    """A single fired element flag with separate confidences.

    ``verification_source`` cites the independent record that backs the flag
    (README v2 Section 5.2): the forensic-science literature finding for a
    discredited method, or the formal disciplinary/misconduct record for a named
    official. It is ``None`` for the case-record-internal categories (informant,
    witness/ID, evidence preservation), whose source is the case record itself.
    """

    category: FlagCategory
    basis: FlagBasis = FlagBasis.DIRECTLY_STATED
    ocr_confidence: float | None = None
    extraction_confidence: float = 0.0
    source_passage: str = ""
    inference_note: str | None = None
    verification_source: str | None = None
    #: Grounded, per-element severity/frequency descriptors (spec v3 §3.4, point
    #: 4): the forensic discreditation tier + citing authority, the official
    #: misconduct type and its gravity, and the repeat-offender finding count.
    #: Each is a labelled descriptor that stays attached to this one element and
    #: is never summed into a case-level number (README v2 §3.1).
    descriptors: dict[str, str] = field(default_factory=dict)


@dataclass
class Case:
    """A case as it moves through the pipeline."""

    case_id: str
    jurisdiction: str
    year: int | None = None
    case_type: str | None = None
    documents: list[Document] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    flags: list[Flag] = field(default_factory=list)
    has_tabular: bool = False


# The standing scope statement that accompanies every attorney-facing output
# (README v2 Section 7). Centralized so every surface uses the exact wording and
# nothing implies a score, rank, or judgment of the case.
SCOPE_STATEMENT: str = (
    "This packet structures available intake and case record information and "
    "flags elements matching documented categories of legal/forensic/procedural "
    "concern. It does not assess guilt, innocence, or likelihood of success on "
    "appeal. The absence of a flag does not indicate the absence of a problem "
    "with the case."
)
