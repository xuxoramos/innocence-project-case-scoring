"""Optional text-normalization step.

Cleans up OCR (or already-digitized) text into ``normalized_text``. If a
document already carries ``normalized_text``, it is left untouched, so an
already-digitized case can skip both OCR and this step.
"""

from __future__ import annotations

import re

from ..models import Case
from .base import ProcessingStep

_WS = re.compile(r"[ \t]+")
_HYPHEN_BREAK = re.compile(r"-\n")


class TextNormalizationStep(ProcessingStep):
    name = "text"

    def applies_to(self, case: Case) -> bool:
        return any(d.normalized_text is None for d in case.documents)

    def run(self, case: Case) -> Case:
        for doc in case.documents:
            if doc.normalized_text is not None:
                continue
            source = doc.ocr_text or ""
            doc.normalized_text = self._normalize(source)
        return case

    @staticmethod
    def _normalize(text: str) -> str:
        text = _HYPHEN_BREAK.sub("", text)
        text = _WS.sub(" ", text)
        return text.strip()
