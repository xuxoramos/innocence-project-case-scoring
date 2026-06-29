"""Processing layer: optional, composable steps.

Order: OCR → text normalization → tabular feature extraction. Every step is
optional so already-digitized cases can skip OCR (and even text/tabular) — the
pipeline only runs steps that are enabled and applicable.
"""

from .base import ProcessingStep
from .ocr import OCRStep
from .pipeline import Pipeline, default_pipeline
from .tabular import TabularStep
from .text import TextNormalizationStep

__all__ = [
    "ProcessingStep",
    "OCRStep",
    "TextNormalizationStep",
    "TabularStep",
    "Pipeline",
    "default_pipeline",
]
