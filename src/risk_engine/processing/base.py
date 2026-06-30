"""Base class for processing steps."""

from __future__ import annotations

import abc

from ..models import Case

_TERMINATORS = ".!?"


def sentence_around(text: str, start: int, end: int) -> str:
    """Return the verbatim sentence containing ``text[start:end]``.

    Flags attach the whole sentence, not the bare matched term, so a human can
    verify the hit in context (README v2 Section 6.3) — e.g. catch a negation
    like "comparison was *not* conclusive" that a bare term would hide.
    """
    left = start
    while left > 0 and text[left - 1] not in _TERMINATORS:
        left -= 1
    right = end
    while right < len(text) and text[right] not in _TERMINATORS:
        right += 1
    if right < len(text):
        right += 1  # include the terminating punctuation
    return text[left:right].strip()


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
