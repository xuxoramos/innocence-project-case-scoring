"""Processing layer: optional, composable steps.

Order: OCR → text normalization → tabular circumstance extraction → forensic
method flags → outcome-determinative record signal → named-official flags. Every
step is optional so already-digitized cases can skip OCR (and even later steps) —
the pipeline only runs steps that are enabled and applicable.
"""

from .base import ProcessingStep
from .determinative import DeterminativeStep
from .forensic import ForensicMethodStep
from .ocr import OCRStep
from .officials import NamedOfficialStep
from .pipeline import Pipeline, default_pipeline
from .tabular import TabularStep
from .text import TextNormalizationStep

__all__ = [
    "ProcessingStep",
    "OCRStep",
    "TextNormalizationStep",
    "TabularStep",
    "ForensicMethodStep",
    "DeterminativeStep",
    "NamedOfficialStep",
    "Pipeline",
    "default_pipeline",
]
