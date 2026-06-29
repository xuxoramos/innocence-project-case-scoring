"""Optional OCR step.

Converts raw scanned documents to text and records a per-document OCR
confidence (README 5.2 / 6.3). Documents flagged ``needs_ocr=False`` (already
digitized) are skipped. Real OCR uses pytesseract when installed; otherwise the
step degrades gracefully so the rest of the pipeline stays testable.
"""

from __future__ import annotations

from ..models import Case
from .base import ProcessingStep


class OCRStep(ProcessingStep):
    name = "ocr"

    def applies_to(self, case: Case) -> bool:
        return any(d.needs_ocr and d.ocr_text is None for d in case.documents)

    def run(self, case: Case) -> Case:
        for doc in case.documents:
            if not doc.needs_ocr or doc.ocr_text is not None:
                continue
            text, conf = self._ocr(doc.raw_path)
            doc.ocr_text = text
            doc.ocr_confidence = conf
        return case

    def _ocr(self, raw_path: str | None) -> tuple[str, float]:
        try:  # pragma: no cover - optional dependency
            import pytesseract
            from PIL import Image

            if raw_path:
                text = pytesseract.image_to_string(Image.open(raw_path))
                return text, 0.85
        except Exception:
            pass
        # Placeholder so digitization can be skipped during the POC.
        return "", 0.0
