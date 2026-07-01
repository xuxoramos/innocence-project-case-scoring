"""Overlay: mark stored exonerations that are **Innocence Project** cases.

This is *external* metadata, not NRE-derived. The National Registry of
Exonerations (the store's source) records **every** US exoneration regardless of
who secured it; the Innocence Project is one organization among many (alongside
other Innocence Network members, conviction-integrity units, and private
counsel). Its public case list (https://innocenceproject.org/all-cases/, scraped
to ``data/raw/innocence_project/all_cases.json``) is joined here by applicant
name + conviction state so the browse/analytics views can distinguish IP-won
cases without inventing any label the NRE itself does not carry.

Matching is deliberately conservative — name **and** state must agree — so a
common name never mistags a different person. Roster entries with no store match
(recent or name-changed exonerees the NRE snapshot predates) are simply left
untagged: an honest NOT_FOUND, never a fabricated match (README v2 3.2 spirit).

Import note: this module never imports :mod:`risk_engine.store` at runtime (only
under ``TYPE_CHECKING``), so ``store`` may import it for the load-time overlay
without a cycle.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    from .store import StoredCase

#: Scraped Innocence Project case list (name + state + exoneration year).
DEFAULT_IP_ROSTER_PATH: Path = settings.raw_dir / "innocence_project" / "all_cases.json"

#: Generational suffixes dropped before name comparison.
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


#: Base URL for an individual Innocence Project case page (slug appended).
IP_CASE_URL_BASE = "https://innocenceproject.org/cases/"
#: The public case list, used when a roster entry has no usable slug.
IP_CASE_LIST_URL = "https://innocenceproject.org/all-cases/"


@dataclass(frozen=True)
class IPCase:
    """One Innocence Project exoneree as scraped from the public case list."""

    name: str
    slug: str
    state: str
    exoneration_year: str | None = None

    @property
    def url(self) -> str:
        """Link to this exoneree's page on the Innocence Project site."""
        return f"{IP_CASE_URL_BASE}{self.slug}/" if self.slug else IP_CASE_LIST_URL


def load_roster(path: str | Path = DEFAULT_IP_ROSTER_PATH) -> list[IPCase]:
    """Load the scraped IP roster, or an empty list when it is not shipped."""
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [
        IPCase(
            name=r["name"],
            slug=r.get("slug", ""),
            state=r.get("state", ""),
            exoneration_year=r.get("exoneration_year"),
        )
        for r in raw
    ]


def _norm(name: str) -> str:
    """Lowercase, drop punctuation and generational suffixes, collapse spaces."""
    s = re.sub(r"[^a-z ]", " ", (name or "").lower())
    return " ".join(t for t in s.split() if t not in _SUFFIXES)


def _surname_key(name: str, state: str) -> tuple[str, str, str] | None:
    """(surname, first-initial, state) key for the fuzzy second pass."""
    toks = _norm(name).split()
    if not toks:
        return None
    return (toks[-1], toks[0][:1], (state or "").lower())


def tag_cases(
    cases: Iterable[StoredCase],
    roster: list[IPCase] | None = None,
) -> int:
    """Set ``innocence_project=True`` on stored cases the IP secured.

    Two conservative passes, both requiring the conviction **state** to agree:

    1. exact normalized-name match, then
    2. surname + first-initial match, applied only when it resolves to a single
       person in that state (so ``Ron Williamson`` reaches ``Ronald Keith
       Williamson`` but an ambiguous surname is skipped).

    Every case is reset to ``False`` first, so re-tagging is idempotent. Returns
    the number of distinct stored cases tagged.
    """
    if roster is None:
        roster = load_roster()
    cases = list(cases)
    for c in cases:
        c.innocence_project = False
    if not roster:
        return 0

    by_name: dict[str, list[StoredCase]] = {}
    by_surname: dict[tuple[str, str, str], list[StoredCase]] = {}
    for c in cases:
        by_name.setdefault(_norm(c.name), []).append(c)
        k = _surname_key(c.name, c.state)
        if k is not None:
            by_surname.setdefault(k, []).append(c)

    tagged: set[int] = set()

    def _mark(group: list[StoredCase]) -> None:
        for c in group:
            if id(c) not in tagged:
                c.innocence_project = True
                tagged.add(id(c))

    for ip in roster:
        state = (ip.state or "").lower()
        exact = [c for c in by_name.get(_norm(ip.name), []) if (c.state or "").lower() == state]
        if exact:
            _mark(exact)
            continue
        key = _surname_key(ip.name, ip.state)
        cand = by_surname.get(key, []) if key is not None else []
        if cand and len({_norm(c.name) for c in cand}) == 1:
            _mark(cand)

    return len(tagged)


def find_ip_case(
    case: StoredCase,
    roster: list[IPCase] | None = None,
) -> IPCase | None:
    """Return the roster entry this stored case matches, or ``None``.

    The reverse of :func:`tag_cases` for a single case, using the same two
    conservative, state-agreeing passes (exact normalized name, then an
    unambiguous surname + first-initial fallback). Used by the detail view to
    surface the exoneree's Innocence Project page and exoneration year; it never
    invents a match the tagging pass would not also make.
    """
    if roster is None:
        roster = load_roster()
    if not roster:
        return None
    target = _norm(case.name)
    state = (case.state or "").lower()
    for ip in roster:
        if _norm(ip.name) == target and (ip.state or "").lower() == state:
            return ip
    key = _surname_key(case.name, case.state)
    if key is None:
        return None
    cand = [ip for ip in roster if _surname_key(ip.name, ip.state) == key]
    if cand and len({_norm(ip.name) for ip in cand}) == 1:
        return cand[0]
    return None
