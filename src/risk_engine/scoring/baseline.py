"""Baseline rule-based scorer.

Ranks cases by the count and confidence of fired flags, weighting inferred
cross-racial flags lower than directly stated ones (README 6.4). It favors
sensitivity over precision (README 6.8). Serves as the reference algorithm to
benchmark learned scorers against — not the final word.
"""

from __future__ import annotations

from ..models import Case, FlagBasis, Worklist
from .base import Scorer, register_scorer


class FlagCountScorer(Scorer):
    name = "flag_count"

    def _weight(self, case: Case) -> float:
        total = 0.0
        for flag in case.flags:
            w = 0.5 if flag.basis is FlagBasis.INFERRED else 1.0
            total += w * flag.extraction_confidence
        return total

    def rank(self, cases: list[Case]) -> Worklist:
        ordered = sorted(cases, key=self._weight, reverse=True)
        return self._to_worklist(ordered)


register_scorer(FlagCountScorer())
