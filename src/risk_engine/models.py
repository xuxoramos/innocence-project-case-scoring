"""Core domain models shared across acquisition, processing and scoring.

These are plain ``dataclasses`` (stdlib only) so the pipeline can be imported
and tested without optional, heavy dependencies. They encode the design
constraints from README.md:

* Confidence is tracked separately for OCR and extraction (README 5.2 / 6.3).
* Each flag carries its verbatim source passage for human verification.
* No single composite score — a case carries the list of its flags, and the
  worklist exposes a *relative rank* only (README 7).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class FlagCategory(str, enum.Enum):
    """NRE-derived structural-failure categories (README 5.1)."""

    FORENSIC_SCIENCE_FLAWS = "forensic_science_flaws"
    WITNESS_RELIABILITY = "witness_reliability"
    CROSS_RACIAL_EYEWITNESS_ID = "cross_racial_eyewitness_id"
    INFORMANT_RISK = "informant_risk"
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
    """A single fired structural-failure flag with separate confidences."""

    category: FlagCategory
    basis: FlagBasis = FlagBasis.DIRECTLY_STATED
    ocr_confidence: float | None = None
    extraction_confidence: float = 0.0
    source_passage: str = ""
    inference_note: str | None = None


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


@dataclass
class WorklistEntry:
    """A ranked entry — relative rank only, never a composite probability."""

    case: Case
    rank: int
    scope_note: str = (
        "This case was flagged based on pattern similarity to documented "
        "exoneration categories. This is not a determination of innocence, and "
        "the absence of a flag does not indicate the absence of error."
    )


@dataclass
class Worklist:
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entries: list[WorklistEntry] = field(default_factory=list)
