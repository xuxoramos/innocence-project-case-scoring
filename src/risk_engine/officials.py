"""Named-official disciplinary/misconduct registry and matcher.

This is the independent verification source for the per-role official-misconduct
flags (``PROSECUTOR_MISCONDUCT``, ``JUDICIAL_MISCONDUCT``, ``POLICE_MISCONDUCT``,
``EXPERT_WITNESS_MISCONDUCT`` — README v2 Sections 5.2 and 6.5). These are the
highest-risk flag categories: because they make individually-identifiable claims
about real prosecutors, judges, police, and analysts, they must be sourced
**exclusively from formal public records** (bar disciplinary actions, court
opinions making findings, published misconduct findings) and every entry must
cite its specific source. An unsourced or informal entry is a defamation
liability, not an asset, and does not belong here.

For that reason no real-person records are hardcoded in this module. The registry
loads from an external data directory (``data/raw/officials/``) that a chapter
populates from formal records; the repository ships only an illustrative,
explicitly-fictional template so the machinery is testable without baking
sensitive claims into source control.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .models import FlagCategory

#: Default directory the registry loads formal official-misconduct records from.
DEFAULT_OFFICIALS_DIR: Path = settings.raw_dir / "officials"

#: Keyword -> role-specific misconduct category. A record's free-text ``role`` is
#: classified by substring so the registry stays human-friendly while flags land
#: in the right per-role category (README v2 6.5).
_ROLE_KEYWORDS: tuple[tuple[tuple[str, ...], FlagCategory], ...] = (
    (("prosecut", "district attorney", "d.a.", "solicitor"), FlagCategory.PROSECUTOR_MISCONDUCT),
    (("judge", "justice", "judicial", "magistrate"), FlagCategory.JUDICIAL_MISCONDUCT),
    (
        ("police", "officer", "detective", "sheriff", "trooper", "law enforcement"),
        FlagCategory.POLICE_MISCONDUCT,
    ),
    (
        ("analyst", "examiner", "expert", "forensic", "scientist", "pathologist", "coroner"),
        FlagCategory.EXPERT_WITNESS_MISCONDUCT,
    ),
)


def category_for_role(role: str) -> FlagCategory | None:
    """Map a free-text official ``role`` to its misconduct category, or ``None``.

    A specific keyword match (prosecutor / judge / police / forensic-analyst)
    wins first. Any other **non-empty** role — the record is already a curated,
    formally-sourced official, so the actor's official status is not in doubt —
    falls into :data:`FlagCategory.OTHER_OFFICIAL_MISCONDUCT` rather than being
    dropped (spec v3 §3.3: the "other official" bucket for actors outside the
    four named roles, e.g. child-welfare or corrections staff). A blank role
    returns ``None`` so the caller skips it: with no stated role there is nothing
    to cite, and guessing one is exactly the defamation risk Section 6.5 guards
    against. Extending the specific roles is a data edit to ``_ROLE_KEYWORDS``.
    """
    text = (role or "").strip().lower()
    if not text:
        return None
    for keywords, category in _ROLE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category
    return FlagCategory.OTHER_OFFICIAL_MISCONDUCT


@dataclass(frozen=True)
class OfficialRecord:
    """One official with a documented, formally-sourced finding against them."""

    name: str  # canonical full name as it appears in formal records
    role: str  # prosecutor / judge / forensic analyst / police, etc.
    finding: str  # short description of the formal finding
    source: str  # the specific formal record citation (required)
    aliases: tuple[str, ...] = ()  # alternate spellings seen in case records

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.source.strip():
            raise ValueError("OfficialRecord requires both a name and a source citation")

    @property
    def match_terms(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    @property
    def citation(self) -> str:
        """The verification string that travels with a fired flag."""
        return f"{self.role}: {self.finding} — {self.source}"


@dataclass(frozen=True)
class OfficialMatch:
    """A registry record matched by name in text, with the matched span."""

    record: OfficialRecord
    start: int
    end: int


@dataclass
class NamedOfficialRegistry:
    """A set of formally-sourced official records, matchable against case text."""

    records: list[OfficialRecord] = field(default_factory=list)
    _compiled: list[tuple[re.Pattern[str], OfficialRecord]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        for record in self.records:
            for term in record.match_terms:
                self._compiled.append(
                    (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), record)
                )

    def __len__(self) -> int:
        return len(self.records)

    def findings_count(self, name: str) -> int:
        """Number of independent formal findings on record for a named official.

        The frequency half of the misconduct descriptor (spec v3 §3.4, point 4):
        each :class:`OfficialRecord` is one formally-sourced finding, so more than
        one record for the same canonical name marks a repeat offender. Matching
        is case-insensitive on the trimmed name. This is a count of documented
        findings, never a score, and it stays attached to that official's flag.
        """
        key = name.strip().lower()
        return sum(1 for record in self.records if record.name.strip().lower() == key)

    def match(self, text: str) -> list[OfficialMatch]:
        """Find registry officials named in ``text`` (first hit per official)."""
        seen: set[str] = set()
        matches: list[OfficialMatch] = []
        for pattern, record in self._compiled:
            if record.name in seen:
                continue
            found = pattern.search(text)
            if found is not None:
                seen.add(record.name)
                matches.append(OfficialMatch(record=record, start=found.start(), end=found.end()))
        return matches

    @classmethod
    def from_records(cls, records: Iterable[OfficialRecord]) -> "NamedOfficialRegistry":
        return cls(records=list(records))

    @classmethod
    def from_dir(cls, path: str | Path = DEFAULT_OFFICIALS_DIR) -> "NamedOfficialRegistry":
        """Load every ``*.json`` file of records from ``path``.

        Each file is a JSON array of objects with keys ``name``, ``role``,
        ``finding``, ``source`` and optional ``aliases``. Files whose stem
        starts with ``_`` are skipped (treat them as templates/notes). A missing
        directory yields an empty registry — an empty registry is a valid state
        (it simply produces no named-official flags).
        """
        directory = Path(path)
        records: list[OfficialRecord] = []
        if directory.is_dir():
            for json_path in sorted(directory.glob("*.json")):
                if json_path.stem.startswith("_"):
                    continue
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                for item in raw:
                    records.append(
                        OfficialRecord(
                            name=item["name"],
                            role=item.get("role", ""),
                            finding=item.get("finding", ""),
                            source=item["source"],
                            aliases=tuple(item.get("aliases", ())),
                        )
                    )
        return cls(records=records)
