"""Named-official flagging step.

Matches officials named in the case record against a
:class:`~risk_engine.officials.NamedOfficialRegistry` of formally-sourced
disciplinary/misconduct records, and emits a role-specific misconduct flag for
each match (prosecutor / judicial / police / expert-witness), citing the
specific formal source as the flag's ``verification_source`` (README v2 Sections
5.2 and 6.5). A record whose role cannot be classified is skipped rather than
guessed. The registry is loaded once from the external officials data directory;
if it is empty (the default when no records have been curated), this step simply
produces no flags.
"""

from __future__ import annotations

from ..models import Case, Flag, FlagBasis
from ..officials import NamedOfficialRegistry, category_for_role
from .base import ProcessingStep, sentence_around

# A name match is high-precision; the heavy lifting is the registry's sourcing.
_NAME_MATCH_CONFIDENCE = 0.9


class NamedOfficialStep(ProcessingStep):
    name = "officials"

    def __init__(self, registry: NamedOfficialRegistry | None = None):
        self.registry = registry if registry is not None else NamedOfficialRegistry.from_dir()

    def applies_to(self, case: Case) -> bool:
        return bool(self.registry) and any(d.normalized_text for d in case.documents)

    def run(self, case: Case) -> Case:
        text = " ".join(d.normalized_text or "" for d in case.documents)
        for match in self.registry.match(text):
            category = category_for_role(match.record.role)
            if category is None:
                continue
            case.flags.append(
                Flag(
                    category=category,
                    basis=FlagBasis.DIRECTLY_STATED,
                    extraction_confidence=_NAME_MATCH_CONFIDENCE,
                    source_passage=sentence_around(text, match.start, match.end),
                    verification_source=match.record.citation,
                )
            )
        return case
