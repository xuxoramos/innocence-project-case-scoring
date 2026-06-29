"""Pipeline orchestration: run enabled, applicable steps in order."""

from __future__ import annotations

from ..models import Case
from .base import ProcessingStep
from .ocr import OCRStep
from .tabular import TabularStep
from .text import TextNormalizationStep


class Pipeline:
    """Runs a configurable, ordered list of optional processing steps.

    Each step decides via ``applies_to`` whether it should run for a given case,
    so already-digitized cases naturally skip OCR (and any other step that is
    not needed).
    """

    def __init__(self, steps: list[ProcessingStep]):
        self.steps = steps

    def process(self, case: Case) -> Case:
        for step in self.steps:
            if step.applies_to(case):
                case = step.run(case)
        return case


def default_pipeline(ocr: bool = True, text: bool = True, tabular: bool = True) -> Pipeline:
    steps: list[ProcessingStep] = []
    if ocr:
        steps.append(OCRStep())
    if text:
        steps.append(TextNormalizationStep())
    if tabular:
        steps.append(TabularStep())
    return Pipeline(steps)
