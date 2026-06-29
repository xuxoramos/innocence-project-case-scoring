"""Base class for processing steps."""

from __future__ import annotations

import abc

from ..models import Case


class ProcessingStep(abc.ABC):
    """A single, optional transformation over a Case.

    ``applies_to`` lets a step skip cases for which it is unnecessary — e.g. the
    OCR step skips documents that are already digitized.
    """

    name: str = "step"

    def applies_to(self, case: Case) -> bool:  # pragma: no cover - trivial default
        return True

    @abc.abstractmethod
    def run(self, case: Case) -> Case:
        ...
