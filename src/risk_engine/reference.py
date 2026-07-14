"""Aggregate reference context from the confirmed-exoneration store.

Descriptive population frequencies only (README v2 §3.2): for a flag category,
how many confirmed exonerations in the reference set carried that NRE
contributing factor. This is a population fact about a category, never a
per-case prediction and never combined into a case-level score (§3.1). It is
surfaced beside a flag purely to give a reviewer context on how common a
documented concern is among known exonerations.

The exoneration store is static between deploys (live intakes never change it),
so the counts are computed once and cached for the process lifetime.
"""

from __future__ import annotations

from functools import lru_cache

from .store import CaseStore


@lru_cache(maxsize=1)
def _category_counts() -> tuple[int, tuple[tuple[str, int], ...]]:
    """(total exonerations, per-category NRE-label counts) — cached per process."""
    store = CaseStore.load()
    return len(store), tuple(store.by_category())


def category_reference() -> dict[str, dict[str, int]]:
    """Map each category value to its population frequency ``{count, total}``.

    ``count`` is the number of confirmed exonerations whose NRE ground-truth
    factors include this category; ``total`` is the size of the reference set.
    Categories that never appear as an NRE factor are simply absent from the map.
    """
    total, counts = _category_counts()
    return {category: {"count": n, "total": total} for category, n in counts}


def reset_cache() -> None:
    """Clear the cached counts (call after the exoneration store is rebuilt)."""
    _category_counts.cache_clear()
