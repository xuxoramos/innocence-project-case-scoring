"""Scoring layer: pluggable, swappable ranking algorithms.

Each algorithm produces a *ranked worklist* — a relative ordering of cases —
not a composite probability (README 7). Register multiple scorers to A/B test
different learning algorithms; a rule-based baseline ships for the POC.
"""

from .base import Scorer, get_scorer, list_scorers, register_scorer
from .baseline import FlagCountScorer

__all__ = ["Scorer", "register_scorer", "get_scorer", "list_scorers", "FlagCountScorer"]
