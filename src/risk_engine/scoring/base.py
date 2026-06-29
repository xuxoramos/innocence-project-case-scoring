"""Scorer interface and registry for swappable learning algorithms."""

from __future__ import annotations

import abc

from ..models import Case, Worklist, WorklistEntry

_SCORERS: dict[str, "Scorer"] = {}


class Scorer(abc.ABC):
    """Ranks cases into a worklist. Implementations may be rule-based or learned.

    The contract is deliberately ordinal: a scorer returns a ranked list, never
    a calibrated probability of innocence. New algorithms (logistic regression,
    gradient boosting, etc.) register here and become interchangeable.
    """

    name: str = "scorer"

    def fit(self, cases: list[Case], labels: list[int]) -> "Scorer":
        """Optional training hook; rule-based scorers may no-op."""
        return self

    @abc.abstractmethod
    def rank(self, cases: list[Case]) -> Worklist:
        ...

    @staticmethod
    def _to_worklist(ordered: list[Case]) -> Worklist:
        wl = Worklist()
        wl.entries = [WorklistEntry(case=c, rank=i + 1) for i, c in enumerate(ordered)]
        return wl


def register_scorer(scorer: Scorer) -> Scorer:
    if not scorer.name:
        raise ValueError("scorer.name must be set")
    _SCORERS[scorer.name] = scorer
    return scorer


def get_scorer(name: str) -> Scorer:
    try:
        return _SCORERS[name]
    except KeyError:
        raise KeyError(f"No scorer registered as {name!r}") from None


def list_scorers() -> list[str]:
    return sorted(_SCORERS)
